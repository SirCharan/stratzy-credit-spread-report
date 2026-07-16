#!/usr/bin/env bash
# Stratzy Almanac — WEEKLY refresh (deep pipeline + AI regeneration).
# Rebuilds the recomputed-from-fills data (needs Chrome logged into Stratzy/DHAN) and regenerates
# the per-algo AI insights + movers portfolio insight, then deploys. Fails SOFT: if the DHAN
# session is dead the deep steps are skipped and the AI still regenerates on the existing data.
# Assumes: you are logged into stratzy.in in local Chrome (DHAN broker) before this runs, and the
# `claude` CLI is authenticated (it drives the AI workflow).
set -uo pipefail

REPO="$HOME/Projects/stratzy-credit-spread-report"
ENV_FILE="$HOME/claude/lakshmi/.env"
LOG="$REPO/insights/refresh_weekly.log"
TEAM="team_D1J75A4fenW3rooePNxiubx9"

cd "$REPO" || { echo "no repo"; exit 1; }
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "===== $(date '+%F %T') weekly refresh ====="

gh auth switch -u SirCharan >/dev/null 2>&1 || true
git pull --rebase --autostash origin main || { echo "git pull failed"; exit 1; }

# 1. DEEP pipeline (auth-gated). Best-effort: see ~/stratzy-archive/REGENERATION_RUNBOOK.md for the
#    canonical fetch (run fetch_option_buying.mjs from /tmp with an exported DHAN Chrome cookie jar).
#    Guard on a run_deep.sh you maintain with the exact fetch invocation; skip cleanly if absent/fails.
if [ -x "$REPO/scripts/run_deep.sh" ]; then
  echo "running deep pipeline…"
  if bash "$REPO/scripts/run_deep.sh"; then echo "deep pipeline ok"; else echo "deep pipeline FAILED — continuing on existing deep data"; fi
else
  echo "no scripts/run_deep.sh — skipping deep refresh, using existing deep data (see REGENERATION_RUNBOOK)"
fi

# 2. facts (numeric, from whatever deep data is current)
python3 generate_algo_facts.py || { echo "facts gen failed"; exit 1; }

# 3. AI regeneration — drive the fan-out Workflow headless via the claude CLI, then capture+merge.
#    (Workflow orchestration lives in Claude Code; a plain shell can't call it directly.)
PROMPT="Run the Stratzy algo-insights workflow to regenerate per-algo AI profiles.
Steps, in order, no questions:
1. Run the Workflow at /Users/ck/stratzy-credit-spread-report/workflows/algo-insights.mjs with args set to the FULL contents of /Users/ck/stratzy-credit-spread-report/insights/_index.json (read that file and pass it as the args object, not a string). Wait for it to complete.
2. python3 /Users/ck/stratzy-credit-spread-report/capture_insights.py <that workflow's transcript dir> /Users/ck/stratzy-credit-spread-report/insights/_judgments.json
3. python3 /Users/ck/stratzy-credit-spread-report/merge_algo_insights.py /Users/ck/stratzy-credit-spread-report/insights/_judgments.json
Then also regenerate the movers portfolio ai_insight into movers/latest.json per movers/README.md. Report the counts."
if command -v claude >/dev/null; then
  echo "invoking claude for AI regen…"
  claude -p "$PROMPT" --permission-mode acceptEdits >>"$LOG" 2>&1 && echo "AI regen done" || echo "AI regen via claude FAILED (regenerate manually)"
else
  echo "claude CLI not found — skipped AI regen"
fi

# 4. also refresh public numbers so everything is same-edition
python3 generate_movers.py || true
python3 generate_universe.py || true

# 5. commit + push everything the run produced
git add -A
if ! git diff --cached --quiet; then
  git commit -m "Weekly: deep data + AI insights $(date '+%F')" || true
  git push origin main || { echo "push failed"; exit 1; }
  echo "pushed"
else
  echo "no change to commit"
fi

# 6. deploy
if vercel --prod --yes --scope "$TEAM" >/dev/null 2>&1; then
  echo "deployed"
else
  echo "deploy failed"
fi
echo "done $(date '+%T')"
