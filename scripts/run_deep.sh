#!/usr/bin/env bash
# Deep fill refresh for the live Stratzy book. Needs a valid session.env
# (run: python3 ~/claude/stratzygrokbot/capture_session.py).
set -euo pipefail
REPO="$HOME/stratzy-credit-spread-report"
cd "$REPO"
python3 fetch_live_fills.py
python3 analyze_credit_spread.py
python3 generate_report.py
python3 generate_diff_data.py
python3 analyze_option_buying.py
python3 generate_option_buying_diff.py
python3 generate_ob_stratzy_data.py
python3 generate_ob_strategy_guide.py || true
python3 generate_equity_curves.py
python3 generate_explore_data.py
python3 generate_correlations.py
python3 generate_algo_facts.py
python3 generate_universe.py
python3 generate_movers.py
echo "deep pipeline ok $(date '+%F %T')"
