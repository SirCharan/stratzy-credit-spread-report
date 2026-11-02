"""research/rank_all.py -> research/ranking.json + research/ranking.csv

Ranks EVERY Stratzy algo (public list, 379) at ck's frame: Rs 5L book,
lots = min(4, 500000 // minimumCapital), windows 12M / 3M ending today.

Tier A (public): stratzy.in/api/web/algo/list `performance` daily % -> cum return, MDD, Calmar,
  converted to Rs on capital = lots x minimumCapital. Charges = trades (avgFrequency) x lots x
  deep-tier median charge/trade/lot for the mapped structure (equity categories: 0.1% of capital).
Tier B (deep, parquet algos): per-trade legs from data/trades_enriched.parquet, P&L re-priced at
  today's lot (NIFTY 65, SENSEX 20), charges per leg from research/charges.py (entry + exit order).
Run: python3 research/rank_all.py [--no-fetch]
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from charges import leg_cost_calibrated  # noqa: E402
from generate_selector import load, r2  # noqa: E402

TODAY = date(2026, 11, 2)
D12, D3 = TODAY - timedelta(days=365), TODAY - timedelta(days=90)
BOOK = 500_000
MAX_LOTS = 4
CUR_LOT = {"NIFTY": 65, "SENSEX": 20}
FLAT_FEE = 100  # book_backtest reconciliation, Rs per lot per trade
URL = "https://stratzy.in/api/web/algo/list"
OPP = {"BUY": "SELL", "SELL": "BUY"}
EQUITY_CATS = {"Investing", "Swing", "Intraday"}
DISP2STRUCT = {
    "Credit Spread": "credit_spread",
    "Short Strangle": "strangle",
    "Short Straddle": "straddle",
    "Option Buying": "naked_buy",
}


def fetch_public(no_fetch: bool) -> list[dict]:
    p = HERE / "algo_list_public.json"
    if not no_fetch:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
        p.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    return json.loads(p.read_text())["data"]


def frame_lots(min_cap) -> tuple[int, bool]:
    """(lots, fits). Algos with minimumCapital > 5L are shown at 1 lot and flagged."""
    if not min_cap:
        return 1, True
    n = min(MAX_LOTS, BOOK // int(min_cap))
    return (n, True) if n >= 1 else (1, False)


def trades_per_year(freq: str | None):
    m = re.match(r"(\d+)\s*trades?/(day|week|month)", freq or "")
    if not m:
        return None
    return int(m.group(1)) * {"day": 250, "week": 52, "month": 12}[m.group(2)]


# ---------------------------------------------------------------- tier B
def leg_rows(legs_json: str, lots: int):
    """(gross_rs, charges_rs) for one trade at `lots`, priced at today's lot size."""
    gross = chg = 0.0
    for lg in json.loads(legs_json):
        q = CUR_LOT.get(lg["underlying"], lg["multiplier"]) * lots
        sgn = 1 if lg["side"] == "BUY" else -1
        gross += sgn * (lg["exit_px"] - lg["entry_px"]) * q
        chg += leg_cost_calibrated(lg["side"], lg["entry_px"], q)
        chg += leg_cost_calibrated(OPP[lg["side"]], lg["exit_px"], q)
    return gross, chg


def copier_shape(legs_json: str) -> bool:
    L = json.loads(legs_json)
    return (
        len(L) == 2
        and len({lg["expiry"] for lg in L}) == 1
        and any(lg["side"] == "SELL" for lg in L)
        and all(lg["underlying"] == "NIFTY" for lg in L)
    )


def eq_stats(pnl: pd.Series) -> dict:
    """pnl ordered by exit time. MDD on cumulative curve starting at 0."""
    if pnl.empty:
        return {"n": 0}
    eq = pnl.cumsum()
    dd = (eq.cummax().clip(lower=0) - eq).max()
    wins, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    net = pnl.sum()
    return {
        "n": int(len(pnl)),
        "net": r2(net, 0),
        "mdd": r2(dd, 0),
        "calmar": r2(net / dd, 2) if dd > 0 else None,
        "pf": r2(wins / losses, 2) if losses > 0 else None,
        "win_rate": r2(100 * (pnl > 0).mean(), 1),
    }


def deep_tier(trades: pd.DataFrame, lots_of: dict) -> tuple[dict, dict]:
    t = trades.copy()
    t["exit_d"] = t["exit_ts_ist"].str[:10]
    g1 = t["legs_json"].map(lambda s: leg_rows(s, 1))
    t["gross1"], t["chg1"] = [x[0] for x in g1], [x[1] for x in g1]
    t["struct"] = t["structure"].replace({"option_buy": "naked_buy", "straddle": "other"})
    t["copier_shape"] = t["legs_json"].map(copier_shape)
    med_chg = t.groupby("structure")["chg1"].median().to_dict()
    med_chg["_all"] = float(t["chg1"].median())
    out = {}
    for aid, a in t.groupby("algo_id"):
        a = a.sort_values("exit_ts_ist")
        L = lots_of.get(aid, 1)
        gl = a["legs_json"].map(lambda s: leg_rows(s, L))
        a = a.assign(grossL=[x[0] for x in gl], chgL=[x[1] for x in gl])
        a["netL"] = a["grossL"] - a["chgL"]
        a["net1"] = a["gross1"] - a["chg1"]
        st = a["struct"].mode().iat[0]
        und = a["underlying"].mode().iat[0]
        shape = float(a["copier_shape"].mean())
        res = {"structure": st, "underlying": und, "lots": L, "copier_shape_share": r2(shape, 2)}
        for tag, start in (("12m", D12), ("3m", D3)):
            w = a[a["entry_date"] >= start.isoformat()]
            s = eq_stats(w["netL"].reset_index(drop=True))
            res[tag] = {
                **s,
                "trades": s["n"],
                "gross_1lot": r2(w["gross1"].sum(), 0),
                "charges_1lot": r2(w["chg1"].sum(), 0),
                "net_1lot": r2(w["net1"].sum(), 0),
                "charge_per_trade_1lot": r2(w["chg1"].mean(), 1) if len(w) else None,
                "expectancy_1lot": r2(w["net1"].mean(), 0) if len(w) else None,
                "gross_frame": r2(w["grossL"].sum(), 0),
                "charges_frame": r2(w["chgL"].sum(), 0),
            }
            res[tag].pop("n", None)
        w12 = a[a["entry_date"] >= D12.isoformat()]
        res["by_bias_net_1lot"] = {
            b: {"n": int(len(g)), "net": r2(g["net1"].sum(), 0)} for b, g in w12.groupby("bias")
        }
        res["by_trend_net_1lot"] = {
            b: {"n": int(len(g)), "net": r2(g["net1"].sum(), 0)} for b, g in w12.groupby("trend_20d")
        }
        out[aid] = res
    return out, {"median_charge_per_trade_1lot": {k: r2(v, 1) for k, v in med_chg.items()}, "_t": t}


# ---------------------------------------------------------------- tier A
def public_tier(a: dict, lots: int, med_chg: dict) -> dict:
    perf = a.get("performance") or {}
    if not perf:
        return {"has_series": False}
    s = pd.Series(perf, dtype=float)
    s.index = pd.to_datetime(s.index, format="%d/%m/%Y")
    s = s.sort_index()
    cap = lots * (a.get("minimumCapital") or 0)
    cat, disp = a.get("category"), a.get("displayCategory")
    struct = "equity" if cat in EQUITY_CATS else DISP2STRUCT.get(disp, "other")
    tpy = trades_per_year(a.get("avgFrequency"))
    if struct == "equity":
        chg_trade = 0.001 * cap  # assumption: 0.1% of capital per round trip
    else:
        chg_trade = lots * med_chg.get({"naked_buy": "option_buy"}.get(struct, struct), med_chg["_all"])
    out = {"has_series": True, "capital_rs": cap, "structure_public": struct,
           "trades_per_year_est": tpy, "charge_per_trade_est": r2(chg_trade, 0)}
    for tag, start in (("12m", D12), ("3m", D3)):
        w = s[s.index >= pd.Timestamp(start)]
        if w.empty:
            out[tag] = {"days_traded": 0}
            continue
        eq = (1 + w / 100).cumprod()
        ret = (eq.iloc[-1] - 1) * 100
        mdd = ((1 - eq / eq.cummax().clip(lower=1)).max()) * 100
        traded = w[w != 0]
        ntr = (tpy * (365 if tag == "12m" else 90) / 365) if tpy else len(traded)
        charges = ntr * chg_trade
        gross_rs = ret / 100 * cap
        pos, neg = traded[traded > 0].sum(), -traded[traded < 0].sum()
        out[tag] = {
            "return_pct": r2(ret, 2),
            "mdd_pct": r2(mdd, 2),
            "calmar": r2(ret / mdd, 2) if mdd > 0 else None,
            "pf_days": r2(pos / neg, 2) if neg > 0 else None,
            "win_day_ratio": r2(100 * (traded > 0).mean(), 1) if len(traded) else None,
            "days_traded": int(len(traded)),
            "gross_rs": r2(gross_rs, 0),
            "charges_rs_est": r2(charges, 0),
            "net_rs": r2(gross_rs - charges, 0),
            "mdd_rs": r2(mdd / 100 * cap, 0),
        }
    return out


def copier_fit(a: dict, deep: dict | None) -> tuple[str, str]:
    if deep:
        ok = (deep["underlying"] == "NIFTY" and deep["structure"] in ("credit_spread", "strangle")
              and deep["copier_shape_share"] >= 0.8)
        return ("FIT" if ok else "NO"), "legs"
    cat, disp = a.get("category"), a.get("displayCategory")
    if cat in EQUITY_CATS or a.get("underlying") != "NIFTY" or disp == "Option Buying" or cat == "Options":
        return "NO", "about"
    txt = (a.get("about") or "").lower()
    if disp in ("Credit Spread", "Short Strangle") or "credit spread" in txt or "strangle" in txt:
        return "UNKNOWN", "about(likely)"
    return "UNKNOWN", "about"


# ---------------------------------------------------------------- reconcile / spot-check
def reconcile_book(t: pd.DataFrame) -> list[dict]:
    bb = load("book_backtest.json")
    rows = []
    for b in bb["algos"]:
        w = t[(t.algo_id == b["id"]) & (t.exit_d >= b["first_fill"]) & (t.exit_d <= bb["window"]["end"])]
        lots = b["lots"]
        net = (w["pnl_rs"].sum() - FLAT_FEE * len(w)) * lots
        rows.append({
            "name": b["name"], "id": b["id"], "lots": lots,
            "book_trades": b["trades"], "ours_trades": int(len(w)),
            "book_net": b["total_net"], "ours_net": r2(net, 0),
            "diff": r2(net - b["total_net"], 0),
            "parquet_first_exit": w.exit_d.min() if len(w) else None,
        })
    return rows


def spot(t: pd.DataFrame, aid: str, lots: int) -> None:
    a = t[(t.algo_id == aid) & (t.entry_date >= D12.isoformat())].sort_values("exit_ts_ist")
    if a.empty:
        print("spot", aid, "no trades")
        return
    print(f"\n== {a.algo_name.iat[0]} ({aid}) lots={lots}")
    print(f"trades {len(a)}  gross/1lot {a.gross1.sum():,.0f}  charges/1lot {a.chg1.sum():,.0f}  "
          f"net/1lot {(a.gross1 - a.chg1).sum():,.0f}")
    r = a.iloc[-1]
    print("sample", r.entry_ts_ist, "->", r.exit_ts_ist)
    for lg in json.loads(r.legs_json):
        q = CUR_LOT.get(lg["underlying"], lg["multiplier"])
        ce, cx = leg_cost_calibrated(lg["side"], lg["entry_px"], q), leg_cost_calibrated(OPP[lg["side"]], lg["exit_px"], q)
        print(f"  {lg['side']:4} {lg['symbol']:22} {lg['entry_px']:>8} -> {lg['exit_px']:>8} qty {q}  "
              f"entry chg {ce:.2f} + exit chg {cx:.2f}")
    print(f"  trade gross {r.gross1:,.2f}  charges {r.chg1:,.2f}  net {r.gross1 - r.chg1:,.2f}")


# ---------------------------------------------------------------- main
def main():
    pub = fetch_public("--no-fetch" in sys.argv)
    trades = pd.read_parquet(ROOT / "data/trades_enriched.parquet")
    lots_of = {a["_id"]: frame_lots(a.get("minimumCapital"))[0] for a in pub}
    deep, meta = deep_tier(trades, lots_of)
    t = meta.pop("_t")
    med = meta["median_charge_per_trade_1lot"]

    rows = []
    for a in pub:
        aid = a["_id"]
        lots, fits = frame_lots(a.get("minimumCapital"))
        pt = public_tier(a, lots, med)
        d = deep.get(aid)
        live = a.get("liveSince")
        age = (TODAY - datetime.fromisoformat(live[:10]).date()).days if live else None
        gates = []
        if not a.get("isActive"):
            gates.append("inactive")
        if a.get("inTesting"):
            gates.append("inTesting")
        if not fits:
            gates.append("minCap>5L")
        if d:
            if d["12m"]["trades"] < 40:
                gates.append("trades12m<40")
        elif (pt.get("12m") or {}).get("days_traded", 0) < 120:
            gates.append("days12m<120")
        if age is None or age < 183:
            gates.append("live<6m")
        fit, src = copier_fit(a, d)
        tier = "deep" if d else "public"
        if d:
            calmar, pf = d["12m"].get("calmar"), d["12m"].get("pf")
            net12, net3, mdd = d["12m"].get("net"), d["3m"].get("net"), d["12m"].get("mdd")
            struct, ntr = d["structure"], d["12m"]["trades"]
        else:
            p12, p3 = pt.get("12m") or {}, pt.get("3m") or {}
            calmar, pf = p12.get("calmar"), p12.get("pf_days")
            net12, net3, mdd = p12.get("net_rs"), p3.get("net_rs"), p12.get("mdd_rs")
            struct, ntr = pt.get("structure_public", "unknown"), p12.get("days_traded")
        rows.append({
            "id": aid, "name": a["name"], "tier": tier, "category": a.get("category"),
            "display_category": a.get("displayCategory"), "underlying": a.get("underlying"),
            "structure": struct, "copier_fit": fit, "copier_fit_source": src,
            "lots": lots, "minimum_capital": a.get("minimumCapital"),
            "capital_rs": lots * (a.get("minimumCapital") or 0),
            "is_active": a.get("isActive"), "in_testing": a.get("inTesting"),
            "live_since": live[:10] if live else None, "live_days": age,
            "gates_failed": gates, "gates_pass": not gates,
            "composite": {"calmar_12m": calmar, "pf_12m": pf, "net_rs_12m": net12,
                          "net_rs_3m": net3, "mdd_rs_12m": mdd, "trades_or_days_12m": ntr},
            "stratzy_reported": {k: a.get(k) for k in (
                "winRatio", "sharpeRatio", "algoScore", "maxDrawdown", "cagr", "oneMonthPnl",
                "threeMonthPnl", "sixMonthPnl", "oneYearPnl", "avgFrequency", "maxSlots")},
            "public": pt,
            "deep": d,
        })

    def ckey(r):
        c = r["composite"]
        return (not r["gates_pass"], -(c["calmar_12m"] if c["calmar_12m"] is not None else -1e9),
                -(c["pf_12m"] or 0))

    for i, r in enumerate(sorted(rows, key=ckey), 1):
        r["rank_composite"] = i
    for i, r in enumerate(sorted(rows, key=lambda r: -(r["composite"]["net_rs_12m"] or -1e12)), 1):
        r["rank_net12m"] = i
    rows.sort(key=lambda r: r["rank_composite"])

    deep_only = [{"id": k, **v} for k, v in deep.items() if k not in {a["_id"] for a in pub}]
    for x in deep_only:
        x["name"] = t.loc[t.algo_id == x["id"], "algo_name"].iat[0]

    recon = reconcile_book(t)
    sel = load("selector.json")
    byid = {r["id"]: r for r in rows}
    sel_check = {k: [{"id": i, "name": (byid.get(i) or {}).get("name"),
                      "rank": (byid.get(i) or {}).get("rank_composite"),
                      "gates_failed": (byid.get(i) or {}).get("gates_failed"),
                      "copier_fit": (byid.get(i) or {}).get("copier_fit")} for i in v]
                 for k, v in sel["shortlist"].items()}

    res = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": TODAY.isoformat(), "windows": {"12m": [D12.isoformat(), TODAY.isoformat()],
                                                 "3m": [D3.isoformat(), TODAY.isoformat()]},
        "frame": {"book_rs": BOOK, "lots": "min(4, 500000 // minimumCapital); >5L shown at 1 lot + gate",
                  "current_lot": CUR_LOT},
        "method": [
            "Deep tier: parquet legs re-priced at today's lot (NIFTY 65, SENSEX 20); charges.py "
            "leg_cost_calibrated on entry + exit of every leg (1 order each); 12M/3M by entry_date; "
            "MDD on net per-trade equity curve (exit order) at frame lots; Calmar = net/MDD.",
            "Public tier: daily % compounded; Rs = % x lots x minimumCapital; charges = avgFrequency "
            "trades x lots x deep median charge/trade for mapped displayCategory structure "
            "(equity categories 0.1% of capital per trade; '--' frequency -> days traded).",
            "Composite: gate-passers first, then 12M Calmar (deep if available else public) desc, PF tie-break.",
            "Copier FIT = NIFTY + credit_spread/strangle + >=80% of trades are 2-leg same-expiry with a SELL.",
        ],
        "median_charge_per_trade_1lot_by_structure": med,
        "algos": rows,
        "deep_only_not_in_public_list": deep_only,
        "reconcile_book_backtest": recon,
        "selector_1nov_check": sel_check,
    }
    (HERE / "ranking.json").write_text(json.dumps(res, indent=1, default=str))

    flat = []
    for r in rows:
        c = r["composite"]
        flat.append({
            "rank_composite": r["rank_composite"], "rank_net12m": r["rank_net12m"], "name": r["name"],
            "id": r["id"], "tier": r["tier"], "structure": r["structure"], "underlying": r["underlying"],
            "copier_fit": r["copier_fit"], "fit_source": r["copier_fit_source"], "lots": r["lots"],
            "capital_rs": r["capital_rs"], "net_rs_12m": c["net_rs_12m"], "net_rs_3m": c["net_rs_3m"],
            "mdd_rs_12m": c["mdd_rs_12m"], "calmar_12m": c["calmar_12m"], "pf_12m": c["pf_12m"],
            "trades_or_days_12m": c["trades_or_days_12m"],
            "pub_ret12_pct": (r["public"].get("12m") or {}).get("return_pct"),
            "pub_mdd12_pct": (r["public"].get("12m") or {}).get("mdd_pct"),
            "deep_charges_12m_frame": (r["deep"] or {}).get("12m", {}).get("charges_frame"),
            "gates_failed": ";".join(r["gates_failed"]),
        })
    pd.DataFrame(flat).to_csv(HERE / "ranking.csv", index=False)

    # ---- console verify
    print("entries", len(rows), "deep filled", sum(r["tier"] == "deep" for r in rows),
          "deep-only extra", len(deep_only), "gate passers", sum(r["gates_pass"] for r in rows))
    print("median charge/trade/1lot", med)
    print("\nRECONCILE (flat Rs100/lot/trade, book window)")
    for x in recon:
        print(f"  {x['name'][:38]:38} lots {x['lots']:>2} tr {x['book_trades']:>4}/{x['ours_trades']:>4} "
              f"book {x['book_net']:>11,.0f} ours {x['ours_net']:>11,.0f} diff {x['diff']:>10,.0f} first {x['parquet_first_exit']}")
    print("\nSELECTOR 1 Nov")
    for k, v in sel_check.items():
        for x in v:
            print(f"  {k:15} {str(x['name'])[:40]:40} rank {x['rank']} fit {x['copier_fit']} fails {x['gates_failed']}")
    for aid in ("687d0a309107a80e07401e5d", "685848b09edddcb829103b9b", "677d7c2a2384694d2347762c"):
        spot(t, aid, lots_of.get(aid, 1))
        d = deep.get(aid)
        if d:
            print("  frame:", {k: d["12m"][k] for k in ("trades", "gross_frame", "charges_frame", "net", "mdd", "calmar", "pf")})


if __name__ == "__main__":
    main()
