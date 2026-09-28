#!/usr/bin/env python3
"""Assemble raw pastAdvices dumps from the scrape_all_algos.py cache.

scrape_all_algos.py fills data/advices/<advisorId>/<YYYY-MM-DD>.json (one JSON array of
pastAdvices items per algo-day) and data/algo_list.json (algo/list metadata for the 121
in-scope algos). This script re-packs that cache into the exact shape the deep pipeline's
analyze_*.py scripts already expect (the shape fetch_option_buying.mjs / fetch_live_fills.py
write to /tmp): a dict keyed by algo name ->
    {algo, trades: [{date: "DD/MM/YYYY", iso: "YYYY-MM-DD", items: [...]}], ok, fail, dates, tradeCount}

Algos are split by category into three bundles (legacy /tmp filenames, so downstream
scripts need only add a RAW_DIR lookup, not a rewrite):
  all_credit_spread_advices.json  - premium-selling universe: Credit Spread, Short Straddle,
                                     Short Strangle, Batman Spread, Iron Condor, Ratio Spread,
                                     Index Strategies
  all_option_buying_advices.json  - Option Buying
  all_other_advices.json          - anything else present in algo_list.json

Written under RAW_DIR (default data/raw/, override with --out or the RAW_DIR env var).
Safe to re-run any time against a partial/growing cache (scrape_all_algos.py may still be
writing) — it only reads what's on disk right now.

    python3 build_raw_from_cache.py [--out data/raw] [--min-trades 10]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ALGO_LIST = ROOT / "data" / "algo_list.json"
ADVICES = ROOT / "data" / "advices"

# category / displayCategory values (lowercased) that make up the premium-selling universe
PREMIUM_SELLING_CATEGORIES = {
    "credit spread",
    "short straddle",
    "short strangle",
    "batman spread",
    "iron condor",
    "ratio spread",
    "index strategies",
}
OPTION_BUYING_CATEGORIES = {"option buying"}

BUCKET_FILES = {
    "cs": "all_credit_spread_advices.json",
    "ob": "all_option_buying_advices.json",
    "other": "all_other_advices.json",
}
BUCKET_LABELS = {"cs": "premium-selling", "ob": "option-buying", "other": "other"}


def classify(algo: dict) -> str:
    cat = (algo.get("displayCategory") or algo.get("category") or "").strip().lower()
    if cat in OPTION_BUYING_CATEGORIES:
        return "ob"
    if cat in PREMIUM_SELLING_CATEGORIES:
        return "cs"
    return "other"


def iso_to_dmy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def build_bundle(algo: dict) -> dict:
    aid = algo.get("_id")
    adir = ADVICES / str(aid)
    trades = []
    ok = 0
    dates = 0
    if adir.is_dir():
        for f in sorted(adir.glob("*.json")):
            dates += 1
            try:
                items = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if items:
                trades.append(
                    {"date": iso_to_dmy(f.stem), "iso": f.stem, "items": items}
                )
                ok += 1
    trade_count = sum(len(t["items"]) for t in trades)
    return {
        "algo": algo,
        "trades": trades,
        "ok": ok,
        "fail": max(dates - ok, 0),
        "dates": dates,
        "tradeCount": trade_count,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--out",
        default=os.environ.get("RAW_DIR", str(ROOT / "data" / "raw")),
        help="output directory for the raw bundles (default data/raw, or $RAW_DIR)",
    )
    ap.add_argument(
        "--min-trades",
        type=int,
        default=10,
        help="report-only: threshold used for the rank-eligible coverage line (default 10)",
    )
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not ALGO_LIST.exists():
        print(f"missing {ALGO_LIST} — run scrape_all_algos.py first", flush=True)
        return 1
    algos = json.loads(ALGO_LIST.read_text())

    buckets: dict[str, dict] = {"cs": {}, "ob": {}, "other": {}}
    coverage: dict[str, list[tuple[str, int, int, int]]] = {
        "cs": [],
        "ob": [],
        "other": [],
    }
    for algo in algos:
        bucket = classify(algo)
        name = algo.get("name") or str(algo.get("_id"))
        bundle = build_bundle(algo)
        buckets[bucket][name] = bundle
        coverage[bucket].append(
            (name, bundle["tradeCount"], bundle["ok"], bundle["dates"])
        )

    for bucket, fname in BUCKET_FILES.items():
        (out_dir / fname).write_text(json.dumps(buckets[bucket]))

    print(f"wrote raw bundles to {out_dir}", flush=True)
    for bucket, label in BUCKET_LABELS.items():
        rows = coverage[bucket]
        n = len(rows)
        with_signal = sum(1 for _, tc, _, _ in rows if tc > 0)
        rank_eligible = sum(1 for _, tc, _, _ in rows if tc >= args.min_trades)
        days_ok = sum(ok for _, _, ok, _ in rows)
        days_total = sum(d for _, _, _, d in rows)
        pct = f"{days_ok / days_total:.1%}" if days_total else "n/a"
        print(
            f"  {label:16s} {n:3d} algos | {with_signal:3d} with >=1 signal | "
            f"{rank_eligible:3d} with >={args.min_trades} (rank-eligible) | "
            f"day-coverage {days_ok}/{days_total} = {pct}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
