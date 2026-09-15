#!/usr/bin/env python3
"""1Y ₹5L-per-name backtest of ck's Stratzy book (17 names: 10 live + 7 parked).

lots = floor(5_00_000 / Stratzy min_capital). Cash until first live fill.
Window: 2025-09-15 → 2026-09-15. Gross + net (₹100 / 1.5 pts per 1-lot trade).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
WINDOW_START = date(2025, 9, 15)
WINDOW_END = date(2026, 9, 15)
BUDGET = 500_000
FEE_INR = 100  # per 1-lot trade (store.js)
FEE_PTS = 1.5
LOT = {"NIFTY": 65, "SENSEX": 20, "BANKNIFTY": 30, "FINNIFTY": 25}

CS_SRC = Path("/tmp/all_credit_spread_analysis.json")
OB_SRC = HERE / "option_buying_analysis.json"
STRANGLE_DUMP = Path("/tmp/all_other_advices.json")
STRANGLE_FILL = Path("/tmp/stratzy_fills/677d7c2a2384694d2347762c.json")
UNI = HERE / "universe.json"
BOOK = HERE / "book_live.json"
NIFTY = HERE / "nifty_daily.json"
OUT = HERE / "book_backtest.json"

STRANGLE_ID = "677d7c2a2384694d2347762c"


def dparse(s: str) -> date | None:
    if not s:
        return None
    s = str(s)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def max_dd(curve: list[dict]) -> float:
    peak = float("-inf")
    dd = 0.0
    for p in curve:
        y = p["y"]
        peak = max(peak, y)
        dd = max(dd, peak - y)
    return round(dd, 2)


def parse_strangle_item(item: dict) -> dict | None:
    legs = item.get("trades") or item.get("legs") or []
    if not legs:
        return None
    if item.get("backtestTrade") is True:
        return None
    pnl = 0.0
    pts = 0.0
    underlying = "NIFTY"
    for leg in legs:
        sym = (leg.get("symbol") or "").upper()
        for u in ("SENSEX", "BANKNIFTY", "FINNIFTY", "NIFTY"):
            if u in sym:
                underlying = u
                break
        side = 1 if (leg.get("transactionType") or "").upper() == "BUY" else -1
        e = float(leg.get("entryPrice") or 0)
        x = float(leg.get("exitPrice") or leg.get("finalExitPrice") or e)
        qty = float(leg.get("quantity") or 1)
        mult = float(leg.get("multiplier") or LOT.get(underlying, 65))
        pnl += side * (x - e) * mult * qty
        pts += side * (x - e) * qty
    closed = item.get("closedOn") or ""
    if "T" in str(closed):
        closed = str(closed).split("T")[0]
    closed = str(closed)[:10]
    if len(closed) != 10:
        return None
    return {
        "closed": closed,
        "points_net": round(pts, 2),
        "calc_pnl_1lot": round(pnl, 2),
        "backtestTrade": False,
    }


def strangle_rows() -> list[dict]:
    blob = None
    if STRANGLE_DUMP.exists():
        d = json.loads(STRANGLE_DUMP.read_text())
        blob = next(iter(d.values()))
    elif STRANGLE_FILL.exists():
        blob = json.loads(STRANGLE_FILL.read_text())
    if not blob:
        return []
    rows = []
    for day in blob.get("trades") or []:
        for item in day.get("items") or []:
            r = parse_strangle_item(item)
            if r:
                rows.append(r)
    return rows


def load_rows() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if CS_SRC.exists():
        for a in json.loads(CS_SRC.read_text()):
            rid = a.get("id")
            rows = [r for r in a.get("rows") or [] if not r.get("backtestTrade")]
            if rid:
                out[rid] = rows
    if OB_SRC.exists():
        for a in json.loads(OB_SRC.read_text()):
            rid = a.get("id")
            rows = [r for r in a.get("rows") or [] if not r.get("backtestTrade")]
            if rid:
                out[rid] = rows
    sr = strangle_rows()
    if sr:
        out[STRANGLE_ID] = sr
    return out


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def main() -> None:
    uni = {a["id"]: a for a in json.loads(UNI.read_text())["algos"]}
    book = json.loads(BOOK.read_text())
    names = list(book["holdings"]) + list(book.get("parked") or [])
    rows_by = load_rows()
    nifty_raw = json.loads(NIFTY.read_text()) if NIFTY.exists() else {}
    nifty_px = {}
    if isinstance(nifty_raw, dict):
        for k, v in nifty_raw.items():
            dd = dparse(k)
            if not dd:
                continue
            cl = v.get("close") if isinstance(v, dict) else v
            if cl is not None:
                nifty_px[dd] = float(cl)
    elif isinstance(nifty_raw, list):
        for p in nifty_raw:
            if not isinstance(p, dict):
                continue
            dd = dparse(p.get("date") or p.get("x"))
            cl = p.get("close") or p.get("y")
            if dd and cl is not None:
                nifty_px[dd] = float(cl)

    algos_out = []
    combined_g = defaultdict(float)
    combined_n = defaultdict(float)
    combined_tr = defaultdict(int)

    for h in names:
        aid = h["id"]
        u = uni.get(aid) or {}
        min_cap = int(u.get("min_capital") or h.get("allocated") or BUDGET)
        if min_cap <= 0:
            min_cap = BUDGET
        lots = BUDGET // min_cap
        deployed = lots * min_cap
        rows = rows_by.get(aid) or []
        by_day_g = defaultdict(float)
        by_day_n = defaultdict(float)
        by_day_tr = defaultdict(int)
        first = last = None
        n_win = 0
        for r in rows:
            dd = dparse(r.get("closed"))
            if not dd or dd < WINDOW_START or dd > WINDOW_END:
                continue
            g = float(r.get("calc_pnl_1lot") or 0) * lots
            n = g - lots * FEE_INR
            by_day_g[dd] += g
            by_day_n[dd] += n
            by_day_tr[dd] += 1
            combined_g[dd] += g
            combined_n[dd] += n
            combined_tr[dd] += 1
            first = dd if first is None else min(first, dd)
            last = dd if last is None else max(last, dd)
            if g > 0:
                n_win += 1
        trades = sum(by_day_tr.values())
        # daily curve over full window (cash until first fill = 0)
        daily_g, daily_n = [], []
        cg = cn = 0.0
        for d in daterange(WINDOW_START, WINDOW_END):
            cg += by_day_g.get(d, 0.0)
            cn += by_day_n.get(d, 0.0)
            iso = d.isoformat()
            daily_g.append({"x": iso, "y": round(cg, 2), "day_pnl": round(by_day_g.get(d, 0.0), 2)})
            daily_n.append({"x": iso, "y": round(cn, 2), "day_pnl": round(by_day_n.get(d, 0.0), 2)})
        total_g = round(sum(by_day_g.values()), 2)
        total_n = round(sum(by_day_n.values()), 2)
        mode = h.get("mode") or ("off" if h.get("isDisabled") else "auto")
        enabled = mode not in ("off", "parked") and not h.get("isDisabled")
        # parked list items use mode off
        if h in (book.get("parked") or []):
            enabled = False
            mode = "off"
        pct = round(100 * total_g / deployed, 2) if deployed else None
        algos_out.append(
            {
                "id": aid,
                "name": h.get("name") or u.get("name"),
                "category": h.get("category") or u.get("category"),
                "enabled": enabled,
                "mode": mode,
                "min_capital": min_cap,
                "lots": lots,
                "deployed_inr": deployed,
                "idle_inr": BUDGET - deployed,
                "first_fill": first.isoformat() if first else None,
                "last_fill": last.isoformat() if last else None,
                "trades": trades,
                "thin": trades < 20,
                "total_gross": total_g,
                "total_net": total_n,
                "max_dd_gross": max_dd(daily_g),
                "max_dd_net": max_dd(daily_n),
                "pct_on_deployed": pct,
                "daily_gross": daily_g,
                "daily_net": daily_n,
            }
        )

    comb_g, comb_n = [], []
    cg = cn = 0.0
    win_days = loss_days = 0
    monthly = defaultdict(lambda: {"gross": 0.0, "net": 0.0, "trades": 0})
    for d in daterange(WINDOW_START, WINDOW_END):
        dg = combined_g.get(d, 0.0)
        dn = combined_n.get(d, 0.0)
        cg += dg
        cn += dn
        iso = d.isoformat()
        comb_g.append({"x": iso, "y": round(cg, 2), "day_pnl": round(dg, 2)})
        comb_n.append({"x": iso, "y": round(cn, 2), "day_pnl": round(dn, 2)})
        if dg > 0:
            win_days += 1
        elif dg < 0:
            loss_days += 1
        m = iso[:7]
        monthly[m]["gross"] += dg
        monthly[m]["net"] += dn
        monthly[m]["trades"] += combined_tr.get(d, 0)

    # nifty indexed to 100 at first available close in window
    nifty_series = []
    base = None
    for d in daterange(WINDOW_START, WINDOW_END):
        px = nifty_px.get(d)
        if px is None:
            continue
        if base is None:
            base = px
        nifty_series.append({"x": d.isoformat(), "y": round(100 * px / base, 3), "close": px})

    deployed = sum(a["deployed_inr"] for a in algos_out)
    idle = 17 * BUDGET - deployed
    algos_out.sort(key=lambda a: -a["total_gross"])

    out = {
        "generated_at": datetime.now().isoformat(),
        "window": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
        "budget_per_algo": BUDGET,
        "n_algos": len(algos_out),
        "n_enabled": sum(1 for a in algos_out if a["enabled"]),
        "n_parked": sum(1 for a in algos_out if not a["enabled"]),
        "notional_inr": 17 * BUDGET,
        "deployed_inr": deployed,
        "idle_inr": idle,
        "fee_inr_per_lot_trade": FEE_INR,
        "fee_pts_per_lot_trade": FEE_PTS,
        "methodology": {
            "lots": "floor(500000 / stratzy min_capital)",
            "clock": "cash until first live fill in window, then lots from that day",
            "pnl": "recomputed fill calc_pnl_1lot × lots; not Stratzy 1Y %",
            "net": "gross − lots × ₹100 per trade",
        },
        "combined": {
            "total_gross": round(sum(combined_g.values()), 2),
            "total_net": round(sum(combined_n.values()), 2),
            "max_dd_gross": max_dd(comb_g),
            "max_dd_net": max_dd(comb_n),
            "win_days": win_days,
            "loss_days": loss_days,
            "pct_on_deployed_gross": round(100 * sum(combined_g.values()) / deployed, 2) if deployed else None,
            "daily_gross": comb_g,
            "daily_net": comb_n,
        },
        "monthly": {
            m: {"gross": round(v["gross"], 2), "net": round(v["net"], 2), "trades": v["trades"]}
            for m, v in sorted(monthly.items())
        },
        "nifty": nifty_series,
        "algos": algos_out,
    }
    # drop daily series nested duplication for file size? Keep — SPA needs them.
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {OUT}  combined gross {out['combined']['total_gross']:+,.0f}  net {out['combined']['total_net']:+,.0f}")
    print(f"  DD gross {out['combined']['max_dd_gross']:,.0f}  deployed {deployed:,.0f}  idle {idle:,.0f}")
    print(f"  win_days {win_days} loss_days {loss_days}")
    for a in algos_out:
        flag = " ⚠" if a["thin"] else ""
        live = "LIVE" if a["enabled"] else "OFF "
        print(
            f"  {live} {a['total_gross']:+10,.0f}  {a['lots']}×  {a['first_fill'] or 'no fills'}  {a['name']}{flag}"
        )


if __name__ == "__main__":
    main()
