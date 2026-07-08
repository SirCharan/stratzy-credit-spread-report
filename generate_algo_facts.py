#!/usr/bin/env python3
"""Assemble a compact, grounded per-algo "facts" record for the AI insight workflow.

For each of the ~50 deep-data algos (explore_data.json) this joins report_data (CS) /
option_buying_stratzy (OB) + equity_curves (per-trade points) + nifty_daily (regime) +
correlations (neighbours) into ONE small JSON the LLM can read without ever touching the
3-5 MB raw files. Pure numeric, no LLM.

The regime bucketing is a faithful PORT of assets/js/regime.js (buildNiftyRegime +
attributeStrategy + tradeStats) so the AI insight agrees with what the deep-dive page renders:
  dir  = trailing-20-trading-day Nifty close return (>=+2% bull / <=-2% bear / else sideways)
  vol  = trailing-20-day realized vol (annualised), tercile-split low/normal/high
  each trade tagged by the regime of its EXIT date (nearest prior trading day).

Output: insights/_facts.json  (intermediate; .vercelignore'd). Consumed by the algo-insights Workflow.
"""

import bisect
import datetime
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "insights")
ANN = math.sqrt(252)
DIR_WINDOW = 20
DIR_BULL = 2.0
DIR_BEAR = -2.0
VOL_WINDOW = 20
DIRS = ["bull", "sideways", "bear"]
VOLS = ["low", "normal", "high"]


def load(name):
    return json.load(open(os.path.join(HERE, name)))


def r2(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


# ---------- regime.js port ----------
def _stdev(arr):
    n = len(arr)
    if n < 2:
        return 0.0
    m = sum(arr) / n
    return math.sqrt(sum((v - m) ** 2 for v in arr) / n)


def _quantile(sorted_arr, q):
    if not sorted_arr:
        return 0.0
    pos = (len(sorted_arr) - 1) * q
    base = math.floor(pos)
    rest = pos - base
    if base + 1 < len(sorted_arr):
        return sorted_arr[base] + rest * (sorted_arr[base + 1] - sorted_arr[base])
    return sorted_arr[base]


def build_nifty_regime(nifty_daily):
    """-> (sorted_dates, {date: {'dir','vol'}}). Mirrors regime.js buildNiftyRegime."""
    dates = sorted(nifty_daily.keys())
    close = [nifty_daily[d]["close"] for d in dates]
    ret = [0.0 if i == 0 else close[i] / close[i - 1] - 1 for i in range(len(close))]
    direction = []
    for i in range(len(dates)):
        if i < DIR_WINDOW:
            direction.append("sideways")
        else:
            chg = (close[i] / close[i - DIR_WINDOW] - 1) * 100
            direction.append(
                "bull" if chg >= DIR_BULL else "bear" if chg <= DIR_BEAR else "sideways"
            )
    rvol = [
        None if i < VOL_WINDOW else _stdev(ret[i - VOL_WINDOW + 1 : i + 1]) * ANN
        for i in range(len(dates))
    ]
    valid = sorted(v for v in rvol if v is not None)
    lo, hi = _quantile(valid, 1 / 3), _quantile(valid, 2 / 3)
    reg = {}
    for i, d in enumerate(dates):
        rv = rvol[i]
        vol = (
            "normal"
            if rv is None
            else "low"
            if rv <= lo
            else "high"
            if rv >= hi
            else "normal"
        )
        reg[d] = {"dir": direction[i], "vol": vol}
    return dates, reg


def nearest_regime(dates, reg, date_str):
    if date_str in reg:
        return reg[date_str]
    idx = bisect.bisect_right(dates, date_str) - 1
    return reg[dates[idx]] if idx >= 0 else None


def _blank():
    return {"trades": 0, "total_pts": 0.0, "wins": 0}


def _finalize(b):
    t = b["trades"]
    return {
        "trades": t,
        "avg_pts": r2(b["total_pts"] / t) if t else None,
        "win_rate": r2(100 * b["wins"] / t) if t else None,
    }


def trade_stats(trade_pts):
    """profit factor + win/loss from [{day_pnl}]. Mirrors regime.js tradeStats."""
    win_sum = loss_sum = 0.0
    win_n = loss_n = 0
    for t in trade_pts or []:
        pnl = t.get("day_pnl") or 0
        if pnl > 0:
            win_sum += pnl
            win_n += 1
        else:
            loss_sum += pnl
            loss_n += 1
    if loss_sum != 0:
        pf = abs(win_sum / loss_sum)
    else:
        pf = math.inf if win_sum > 0 else 0
    return {
        "profit_factor": None if pf == math.inf else r2(pf),
        "profit_factor_inf": pf == math.inf,
    }


def attribute(trade_pts, dates, reg):
    dir_b = {k: _blank() for k in DIRS}
    vol_b = {k: _blank() for k in VOLS}
    tagged = 0
    for t in trade_pts or []:
        pnl = t.get("day_pnl") or 0
        r = nearest_regime(dates, reg, t["x"])
        if not r:
            continue
        tagged += 1
        for bucket, key in ((dir_b, r["dir"]), (vol_b, r["vol"])):
            bucket[key]["trades"] += 1
            bucket[key]["total_pts"] += pnl
            if pnl > 0:
                bucket[key]["wins"] += 1
    return (
        {k: _finalize(v) for k, v in dir_b.items()},
        {k: _finalize(v) for k, v in vol_b.items()},
        tagged,
    )


# ---------- neighbours ----------
def neighbours(aid, corr, n=5):
    matrix = corr["matrix"]
    row = matrix.get(aid)
    if not row:
        return {"similar": [], "opposite": []}
    name_by_id = {a["id"]: a.get("short") or a["id"] for a in corr["algos"]}
    pairs = [(oid, r) for oid, r in row.items() if oid != aid and r is not None]
    pairs.sort(key=lambda x: x[1])  # ascending corr
    opp = [{"id": i, "name": name_by_id.get(i, i), "corr": r2(r)} for i, r in pairs[:n]]
    sim = [
        {"id": i, "name": name_by_id.get(i, i), "corr": r2(r)}
        for i, r in reversed(pairs[-n:])
    ]
    return {"similar": sim, "opposite": opp}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    explore = load("explore_data.json")["algos"]
    report = {a["id"]: a for a in load("report_data.json")["algos"]}
    ec = {a["id"]: a for a in load("equity_curves.json")["algos"]}
    corr = load("correlations.json")
    nifty = load("nifty_daily.json")
    dates, reg = build_nifty_regime(nifty)

    # OB per-algo strategy detail (big file — load once, index by id)
    try:
        ob = {a["id"]: a for a in load("option_buying_stratzy.json")["algos"]}
    except Exception:
        ob = {}

    rows = []
    for e in explore:
        aid = e["id"]
        cat = e.get("category")
        eqa = ec.get(aid)
        trade_pts = ((eqa or {}).get("curves") or {}).get("trade_pts") if eqa else None
        dir_b, vol_b, tagged = (
            attribute(trade_pts, dates, reg) if trade_pts else ({}, {}, 0)
        )
        pf = (
            trade_stats(trade_pts)
            if trade_pts
            else {"profit_factor": None, "profit_factor_inf": False}
        )

        row = {
            "id": aid,
            "name": e.get("name"),
            "short": e.get("short_name"),
            "category": cat,
            "underlying": e.get("underlying"),
            "style": e.get("style"),
            "style_label": e.get("style_label"),
            "one_liner": e.get("one_liner"),
            "side_mix": {"ce_pct": r2(e.get("ce_pct")), "pe_pct": r2(e.get("pe_pct"))},
            "win_loss": {
                "win_rate": r2(e.get("all_time_wr") or e.get("win_ratio_pct")),
                "trades": e.get("all_time_trades"),
                "profit_factor": pf["profit_factor"],
                "profit_factor_inf": pf["profit_factor_inf"],
            },
            "regime": {"dir": dir_b, "vol": vol_b, "trades_tagged": tagged},
            "neighbours": neighbours(aid, corr),
            "has_regime": bool(tagged),
        }

        if cat == "credit_spread" and aid in report:
            ts = report[aid].get("trade_structure", {})
            at = report[aid].get("all_time", {})
            row["trade_structure"] = {
                "spread_type": ts.get("spread_type"),
                "avg_strike_width": ts.get("avg_strike_width"),
                "avg_entry_credit_pts": r2(ts.get("avg_entry_credit_pts")),
                "iron_condor_pct": r2(ts.get("iron_condor_pct")),
                "side_summary": ts.get("side_summary"),
                "ce_only_pct": r2(ts.get("ce_only_pct")),
                "pe_only_pct": r2(ts.get("pe_only_pct")),
                "both_pct": r2(ts.get("both_pct")),
            }
            row["win_loss"].update(
                {
                    "win_rate": r2(at.get("win_rate")) or row["win_loss"]["win_rate"],
                    "avg_win_pts": r2(at.get("avg_win_pts")),
                    "avg_loss_pts": r2(at.get("avg_loss_pts")),
                    "trades": at.get("trades") or row["win_loss"]["trades"],
                    "trades_per_month": r2(at.get("trades_per_month")),
                    "max_drawdown_pts": r2(at.get("max_drawdown_pts")),
                }
            )
        elif cat == "option_buying" and aid in ob:
            oba = ob[aid]
            strat = oba.get("strategy", {}) or {}
            summ = (oba.get("summary", {}) or {}).get("all", {}) or {}
            row["ob_strategy"] = {
                "family_title": strat.get("family_title"),
                "dominant_moneyness": strat.get("dominant_moneyness"),
                "trend_label": strat.get("trend_label"),
                "market_fit": strat.get("market_fit"),
                "ce_pct": r2(strat.get("ce_pct")),
                "pe_pct": r2(strat.get("pe_pct")),
                "trades_per_month": r2(strat.get("trades_per_month")),
                "avg_frequency": strat.get("avg_frequency"),
            }
            row["win_loss"].update(
                {
                    "win_rate": r2(summ.get("win_rate")) or row["win_loss"]["win_rate"],
                    "avg_win_pts": r2(summ.get("avg_win_pts")),
                    "avg_loss_pts": r2(summ.get("avg_loss_pts")),
                    "trades": summ.get("trades") or row["win_loss"]["trades"],
                    "trades_per_month": r2(strat.get("trades_per_month")),
                }
            )
        rows.append(row)

    out = {
        "generated_at": datetime.date.today().isoformat(),
        "n_algos": len(rows),
        "n_with_regime": sum(1 for r in rows if r["has_regime"]),
        "regime_source_days": len(dates),
        "algos": rows,
    }
    path = os.path.join(OUT_DIR, "_facts.json")
    json.dump(out, open(path, "w"), separators=(",", ":"), ensure_ascii=False)

    # per-algo files (one small JSON each) + an index — the AI workflow's agents Read these
    # (workflow scripts have no filesystem access, so we pass only the tiny index as args).
    facts_dir = os.path.join(OUT_DIR, "facts")
    os.makedirs(facts_dir, exist_ok=True)
    index = []
    for r in rows:
        fp = os.path.join(facts_dir, f"{r['id']}.json")
        json.dump(r, open(fp, "w"), separators=(",", ":"), ensure_ascii=False)
        index.append(
            {
                "id": r["id"],
                "short": r["short"],
                "name": r["name"],
                "category": r["category"],
                "path": fp,
            }
        )
    json.dump(
        {"generated_at": out["generated_at"], "algos": index},
        open(os.path.join(OUT_DIR, "_index.json"), "w"),
        separators=(",", ":"),
        ensure_ascii=False,
    )
    print(f"wrote {path} + {len(index)} per-algo files + _index.json")
    print(
        f"  {out['n_algos']} algos, {out['n_with_regime']} with regime buckets, "
        f"{len([r for r in rows if r['neighbours']['similar']])} with neighbours"
    )
    # tiny sanity dump
    s = rows[0]
    print(
        f"  sample [{s['name']}] cat={s['category']} bias(ce/pe)={s['side_mix']} "
        f"dir_bull={s['regime']['dir'].get('bull')} pf={s['win_loss']['profit_factor']}"
    )


if __name__ == "__main__":
    main()
