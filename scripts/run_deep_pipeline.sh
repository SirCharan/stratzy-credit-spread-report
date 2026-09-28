#!/usr/bin/env bash
# Deep pipeline over the FULL scraped-algo cache (data/advices/ + data/algo_list.json),
# not the old hand-picked 25 credit-spread + 25 option-buying lists.
#
# Replaces CONTEXT.md regeneration-pipeline step 1 (fetch_option_buying.mjs, which needed
# a live DHAN Chrome cookie jar) with build_raw_from_cache.py, which re-packs whatever
# scrape_all_algos.py has written to data/advices/ so far into the same /tmp-shaped raw
# bundles the analyze_*.py / generate_*.py scripts already expect (now under data/raw/,
# via the RAW_DIR env var — see build_raw_from_cache.py). Safe to run against a partial,
# still-growing cache.
#
# analyze_credit_spread.py is inserted right after build_raw_from_cache.py: CONTEXT.md's
# numbered list only names it implicitly (it is generate_report.py's producer, the
# credit-spread-side twin of analyze_option_buying.py, which folds analysis + report in
# one step). Everything else follows CONTEXT.md's 11-step order, then generate_algo_facts.py
# — the AI-insight workflow (workflows/algo-insights.mjs, capture_insights.py,
# merge_algo_insights.py) is intentionally SKIPPED, per instructions.
#
# Usage: scripts/run_deep_pipeline.sh
#   RAW_DIR=data/raw               (env, optional override; each script defaults here already)
#   MIN_TRADES_RANKED=10           (env, optional override; algos below this are "thin")

set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

export RAW_DIR="${RAW_DIR:-$REPO/data/raw}"
export MIN_TRADES_RANKED="${MIN_TRADES_RANKED:-10}"

echo "== build_raw_from_cache.py (RAW_DIR=$RAW_DIR) =="
python3 build_raw_from_cache.py

echo "== analyze_credit_spread.py =="
python3 analyze_credit_spread.py

echo "== 2. generate_report.py =="
python3 generate_report.py

echo "== 3. generate_diff_data.py =="
python3 generate_diff_data.py

echo "== 4. analyze_option_buying.py =="
python3 analyze_option_buying.py

echo "== 5. generate_option_buying_diff.py =="
python3 generate_option_buying_diff.py

echo "== 6. generate_ob_strategy_guide.py =="
python3 generate_ob_strategy_guide.py

echo "== 7. generate_ob_stratzy_data.py =="
python3 generate_ob_stratzy_data.py

echo "== 8. generate_equity_curves.py =="
python3 generate_equity_curves.py

echo "== 9. generate_explore_data.py =="
python3 generate_explore_data.py

echo "== 10. generate_correlations.py =="
python3 generate_correlations.py

echo "== 11. generate_universe.py =="
python3 generate_universe.py

echo "== 12. generate_algo_facts.py (AI insight workflow skipped) =="
python3 generate_algo_facts.py

echo "deep pipeline ok $(date '+%F %T')"
