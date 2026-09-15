#!/usr/bin/env python3
"""Turn pastAdvices dump → /tmp/all_credit_spread_analysis.json (generate_report.py input)."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

IN_PATH = Path("/tmp/all_credit_spread_advices.json")
OUT_PATH = Path("/tmp/all_credit_spread_analysis.json")
LOT = {"NIFTY": 65, "SENSEX": 20, "BANKNIFTY": 30, "FINNIFTY": 25}


def underlying_from_symbol(symbol: str) -> str:
    s = (symbol or "").upper()
    for u in ("SENSEX", "BANKNIFTY", "FINNIFTY", "NIFTY"):
        if u in s:
            return u
    return "NIFTY"


def parse_item(item: dict, algo_underlying: str) -> dict | None:
    legs = item.get("legs") or item.get("trades") or []
    if not legs:
        return None
    underlying = algo_underlying
    for leg in legs:
        u = underlying_from_symbol(leg.get("symbol") or "")
        if u:
            underlying = u
            break
    lot = LOT.get(underlying, 65)
    points = 0.0
    pnl = 0.0
    for leg in legs:
        side = 1 if (leg.get("transactionType") or "").upper() == "BUY" else -1
        e = float(leg.get("entryPrice") or 0)
        x = float(leg.get("exitPrice") or e)
        qty = float(leg.get("quantity") or 1)
        pnl += side * (x - e) * lot * qty
        points += side * (x - e) * qty
    closed = item.get("closedOn") or item.get("date") or ""
    if "T" in str(closed):
        closed = str(closed).split("T")[0]
    return {
        "closed": str(closed)[:10],
        "name": item.get("name") or "",
        "underlying": underlying,
        "points_net": round(points, 2),
        "calc_pnl_1lot": round(points * lot, 2),
        "margin": item.get("marginRequired"),
        "backtestTrade": item.get("backtestTrade") is True,
        "legs": legs,
        "signalPnl": item.get("signalPnl") or item.get("pnl"),
    }


def summarize(rows: list[dict]) -> dict:
    live = [r for r in rows if not r.get("backtestTrade")]
    if not live:
        return {}
    pts = sum(r["points_net"] for r in live)
    inr = sum(r["calc_pnl_1lot"] for r in live)
    wins = sum(1 for r in live if r["points_net"] > 0)
    return {
        "trades": len(live),
        "total_points": round(pts, 1),
        "total_inr": round(inr),
        "wins": wins,
        "losses": sum(1 for r in live if r["points_net"] < 0),
        "first_trade": min((r["closed"] for r in live if r["closed"]), default=""),
        "last_trade": max((r["closed"] for r in live if r["closed"]), default=""),
    }


def main() -> None:
    raw = json.loads(IN_PATH.read_text())
    out = []
    for name, bundle in raw.items():
        algo = bundle.get("algo") or {}
        underlying = algo.get("underlying") or "NIFTY"
        rows = []
        for day in bundle.get("trades") or []:
            for item in day.get("items") or []:
                row = parse_item(item, underlying)
                if row and row["closed"]:
                    rows.append(row)
        rows.sort(key=lambda r: r["closed"])
        live = summarize(rows)
        if not live:
            continue
        out.append(
            {
                "id": algo.get("_id") or algo.get("id"),
                "name": algo.get("name") or name,
                "underlying": underlying,
                "liveSince": algo.get("liveSince"),
                "live": live,
                "rows": rows,
            }
        )
    OUT_PATH.write_text(json.dumps(out))
    print(f"wrote {OUT_PATH} algos={len(out)}")
    for a in sorted(out, key=lambda x: -x["live"]["total_points"])[:8]:
        print(f"  {a['live']['total_points']:+8.1f} pts  {a['name']}  last={a['live']['last_trade']}")


if __name__ == "__main__":
    main()
