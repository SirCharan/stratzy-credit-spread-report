#!/usr/bin/env python3
"""Merge the AI workflow's judgment fields with deterministic facts → algo_insights.json.

The algo-insights Workflow emits ONLY plain-English judgment fields per algo (summary, style,
hold, makes_money_when, ...). This script re-attaches the deterministic numbers from
insights/_facts.json (win/loss, regime buckets, correlation neighbours) and computes `bias`
here (never trusting the LLM for numbers), producing the committed algo_insights.json the SPA reads.

Usage:  python3 merge_algo_insights.py <judgments.json>
  judgments.json = {"generated_at":..., "algos":[{"id":..,"profile":{...judgment fields}}, ...]}
"""

import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FACTS = os.path.join(HERE, "insights", "_facts.json")
OUT = os.path.join(HERE, "algo_insights.json")

JUDGMENT_KEYS = [
    "summary",
    "what_it_trades",
    "style",
    "style_evidence",
    "expiry",
    "hold",
    "makes_money_when",
    "iv_sensitivity",
]


def bias_from(frow):
    """Deterministic put/call bias. Prefer CS spread-side mix, else explore ce/pe."""
    ts = frow.get("trade_structure") or {}
    both = ts.get("both_pct")
    ce = ts.get("ce_only_pct")
    pe = ts.get("pe_only_pct")
    if ce is None or pe is None:
        sm = frow.get("side_mix") or {}
        ce, pe = sm.get("ce_pct"), sm.get("pe_pct")
    if both is not None and both >= 40:
        return "both-sided / neutral"
    if ce is None or pe is None:
        return "unknown"
    if ce >= 57:
        return "call-heavy"
    if pe >= 57:
        return "put-heavy"
    return "balanced"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: merge_algo_insights.py <judgments.json>")
    judgments = json.load(open(sys.argv[1]))
    facts = {a["id"]: a for a in json.load(open(FACTS))["algos"]}

    jmap = {}
    for entry in judgments.get("algos", []):
        p = entry.get("profile") or {}
        jmap[entry.get("id") or p.get("id")] = p

    out_algos = {}
    for aid, frow in facts.items():
        p = jmap.get(aid)
        if not p:
            continue  # no AI profile generated for this algo
        wl = frow.get("win_loss") or {}
        out_algos[aid] = {
            "id": aid,
            "name": frow.get("name"),
            "short": frow.get("short"),
            "category": frow.get("category"),
            # judgment (LLM)
            **{k: p.get(k) for k in JUDGMENT_KEYS},
            # deterministic (facts)
            "bias": bias_from(frow),
            "frequency_per_month": wl.get("trades_per_month"),
            "win_loss": {
                "win_rate": wl.get("win_rate"),
                "avg_win_pts": wl.get("avg_win_pts"),
                "avg_loss_pts": wl.get("avg_loss_pts"),
                "profit_factor": wl.get("profit_factor"),
                "profit_factor_inf": wl.get("profit_factor_inf", False),
                "trades": wl.get("trades"),
            },
            "regime": frow.get("regime"),
            "similar": (frow.get("neighbours") or {}).get("similar", []),
            "opposite": (frow.get("neighbours") or {}).get("opposite", []),
        }

    out = {
        "generated_at": judgments.get("generated_at")
        or datetime.date.today().isoformat(),
        "model": judgments.get("model", "claude (workflow)"),
        "n": len(out_algos),
        "algos": out_algos,
    }
    json.dump(out, open(OUT, "w"), separators=(",", ":"), ensure_ascii=False)
    print(f"wrote {OUT} — {len(out_algos)} algo profiles")
    miss = [f["name"] for i, f in facts.items() if i not in out_algos]
    if miss:
        print(
            f"  {len(miss)} facts algos had no AI profile: {miss[:5]}{'…' if len(miss) > 5 else ''}"
        )


if __name__ == "__main__":
    main()
