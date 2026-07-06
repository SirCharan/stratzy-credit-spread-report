#!/usr/bin/env python3
"""Pull ALL Stratzy algos (public API) into universe.json with rich headline/backtest
metrics. Flags the ~50 algos that also have deep recomputed per-trade data."""

import json, sys, urllib.request, datetime, os

API = "https://stratzy.in/api/web/algo/list"
HERE = os.path.dirname(os.path.abspath(__file__))


def fetch():
    req = urllib.request.Request(API, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["data"]


def num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def main():
    raw = fetch()
    # deep-data ids (the 50 with recomputed per-trade + curves)
    deep = {}
    try:
        ex = json.load(open(os.path.join(HERE, "explore_data.json")))
        deep = {a["id"]: a for a in ex["algos"]}
    except Exception:
        pass

    algos = []
    for a in raw:
        _id = a.get("_id")
        d = deep.get(_id)
        algos.append(
            {
                "id": _id,
                "name": a.get("name"),
                "category": a.get("displayCategory"),
                "risk": a.get("risk"),
                "underlying": a.get("underlying"),
                "house": a.get("researchHouseName"),
                # returns across windows
                "ret_1y": num(a.get("oneYearPnl")),
                "ret_6m": num(a.get("sixMonthPnl")),
                "ret_3m": num(a.get("threeMonthPnl")),
                "ret_1m": num(a.get("oneMonthPnl")),
                "ret_7d": num(a.get("sevenDayPnl")),
                # quality / risk-adjusted
                "win_ratio": num(a.get("winRatio")),
                "rr": num(a.get("riskRewardRatio")),
                "sharpe": num(a.get("sharpeRatio")),
                "sharpe_bt": num(a.get("backtestSharpeRatio")),
                "max_dd": num(a.get("maxDrawdown")),
                "cagr": num(a.get("cagr")),
                "ann_ret": num(a.get("annualizedReturns")),
                "recovery_days": num(a.get("avgTimeToRecovery")),
                "score": num(a.get("algoScore")),
                "rank": a.get("algoRank"),
                # capital / activity
                "min_capital": a.get("minimumCapital"),
                "avg_capital": a.get("avgCapital"),
                "max_capital": a.get("maximumCapital"),
                "frequency": a.get("avgFrequency"),
                "deploy_count": a.get("deployCount"),
                "live_since": a.get("liveSince"),
                "last_traded": a.get("lastTradedOn"),
                "in_testing": bool(a.get("inTesting")),
                # deep-data crossref
                "deep": _id in deep,
                "all_time_pts": (d or {}).get("all_time_pts"),
                "ytd_2026_pts": (d or {}).get("ytd_2026_pts"),
            }
        )

    cats = {}
    for a in algos:
        cats[a["category"]] = cats.get(a["category"], 0) + 1

    out = {
        "generated_at": datetime.date.today().isoformat(),
        "source": "stratzy.in/api/web/algo/list (public)",
        "total": len(algos),
        "deep_count": sum(1 for a in algos if a["deep"]),
        "categories": cats,
        "algos": algos,
    }
    path = os.path.join(HERE, "universe.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    print(f"wrote {path}: {len(algos)} algos, {out['deep_count']} deep")
    print("categories:", cats)


if __name__ == "__main__":
    main()
