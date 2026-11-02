#!/usr/bin/env bash
# Stratzy Almanac — WEEKLY refresh, fully unattended. See scripts/README-weekly.md.
# Order: auth sync -> scrape -> live fills -> regime data -> generators -> rank -> (deep/AI regen)
#        -> commit/push -> deploy -> Telegram digest. A failed step logs and continues;
#        dead auth (sync_cookie exit 2) stops the run after a Telegram note.
# --dry-run: print each step's command, run only `sync_cookie.py --check`. Nothing else.
set -uo pipefail

DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
REPO="$HOME/stratzy-credit-spread-report"
ENV_FILE="$HOME/claude/lakshmi/.env"
TEAM="team_QUgI2tENi0Wo8L7m2s2GoATi"
SITE="https://stratzy-credit-spread-report.vercel.app"
TODAY="$(date '+%F')"
cd "$REPO" || { echo "no repo"; exit 1; }
mkdir -p logs
LOG="$REPO/logs/weekly-$TODAY.log"
if [ "$DRY" = 1 ]; then LOG=/dev/stdout; else exec >>"$LOG" 2>&1; fi
ts() { echo "[$(date '+%T')] $*"; }
# step <label> <cmd...>: log, run (or just print under --dry-run), never abort the run
step() { local l="$1"; shift; ts "STEP $l: $*"; [ "$DRY" = 1 ] && return 0; "$@" && ts "ok $l" || ts "FAILED $l — continuing"; }
envv() { grep -m1 "^$1=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'\'' '; }
tg() { local bt ch; bt="$(envv STRATZY_TG_BOT_TOKEN)"; ch="$(envv STRATZY_TG_CHAT_ID)"
  [ -n "$bt" ] && [ -n "$ch" ] && curl -s -X POST "https://api.telegram.org/bot${bt}/sendMessage" \
    --data-urlencode "chat_id=${ch}" --data-urlencode "text=$1" >/dev/null && ts "digest sent" || ts "digest skipped/failed"; }

ts "===== weekly refresh $TODAY (dry=$DRY) ====="
[ "$DRY" = 0 ] && { gh auth switch -u SirCharan >/dev/null 2>&1 || true
  git pull --rebase --autostash origin main || ts "git pull failed (continuing)"; }
ts "STEP gh+pull: gh auth switch -u SirCharan; git pull --rebase --autostash origin main"

# 1. auth sync + mint probe
if [ "$DRY" = 1 ]; then
  ts "STEP auth-sync: python3 research/sync_cookie.py   (dry-run runs --check only)"
  python3 research/sync_cookie.py --check
  AUTH_LEFT="$(python3 research/sync_cookie.py --check | sed -n 's/^days_left=//p')"
else
  SYNC_OUT="$(python3 research/sync_cookie.py 2>&1)"; RC=$?
  echo "$SYNC_OUT"
  AUTH_LEFT="$(echo "$SYNC_OUT" | sed -n 's/^days_left=//p')"
  if [ "$RC" = 2 ]; then
    ts "auth dead: log in + capture_session.py — stopping"
    tg "Stratzy weekly $TODAY: AUTH DEAD. Log in + run capture_session.py. Nothing refreshed."
    exit 2
  fi
fi

# keep the previous selector for the digest diff
[ "$DRY" = 1 ] && ts "STEP keep-prev-selector: cp selector.json /tmp/selector.prev.json" || cp selector.json /tmp/selector.prev.json 2>/dev/null

# optional deep pipeline (needs scripts/run_deep.sh; skipped if absent)
if [ -x scripts/run_deep.sh ]; then step deep bash scripts/run_deep.sh; else ts "no scripts/run_deep.sh — deep refresh skipped"; fi

# 2-3. scrape + live fills
SCRAPE_TMP="$(mktemp)"
if [ "$DRY" = 1 ]; then ts "STEP scrape: python3 scrape_all_algos.py --days 400 --delay 0.4"
else ts "STEP scrape"; python3 scrape_all_algos.py --days 400 --delay 0.4 2>&1 | tee "$SCRAPE_TMP" || ts "FAILED scrape — continuing"; fi
step fills python3 fetch_live_fills.py

# 4. regime data (nifty_vix_daily.json, iv_daily.json, regime_panel.json + trades_enriched.parquet)
step nifty-vix python3 fetch_market_data.py
step iv-bhavcopy python3 fetch_bhavcopy.py
step regime-panel python3 regime_study.py

# 5. generators + ranking
step movers python3 generate_movers.py
step universe python3 generate_universe.py
step book-backtest python3 generate_book_backtest.py
step selector python3 generate_selector.py
step algo-facts python3 generate_algo_facts.py
step rank python3 research/rank_all.py

# AI insight regen (kept from the old weekly job)
if command -v claude >/dev/null; then
  step ai-regen claude -p "Run the Stratzy algo-insights workflow at $REPO/workflows/algo-insights.mjs with args = full contents of $REPO/insights/_index.json; then python3 $REPO/capture_insights.py <transcript dir> $REPO/insights/_judgments.json; then python3 $REPO/merge_algo_insights.py $REPO/insights/_judgments.json. No questions." --permission-mode acceptEdits
else ts "claude CLI not found — AI regen skipped"; fi

# 6. commit + push (same commands as refresh_daily.sh) + deploy
ts "STEP commit: git add -u -- ':(glob)*.json' movers insights research/ranking.csv research/ranking.json; git commit -m 'Almanac weekly refresh $TODAY'; git push origin main"
if [ "$DRY" = 0 ]; then
  git add -u -- ':(glob)*.json' movers insights research/ranking.csv research/ranking.json
  if ! git diff --cached --quiet; then
    git commit -m "Almanac weekly refresh $TODAY" || true
    git push origin main || ts "push FAILED (origin stale/forbidden? ck's remote to fix) — continuing"
  else ts "no change to commit"; fi
fi
ts "STEP deploy: vercel --prod --yes --token \$VERCEL_TOKEN_CKDELTA --scope $TEAM"
if [ "$DRY" = 0 ]; then
  VT="$(envv VERCEL_TOKEN_CKDELTA)"
  if [ -n "$VT" ]; then vercel --prod --yes --token "$VT" --scope "$TEAM" >/dev/null && ts deployed || ts "deploy failed"
  else ts "no VERCEL_TOKEN_CKDELTA — skipped deploy"; fi
fi
ts "STEP verify-live: curl $SITE/book_backtest.json (log window)"
if [ "$DRY" = 0 ]; then
  curl -s "$SITE/book_backtest.json" | python3 -c "import sys,json;print('live book window:',json.load(sys.stdin).get('window'))" 2>&1 | sed "s/^/[live] /" || ts "live check failed"
fi

# 7. Telegram digest
ts "STEP digest: telegram (book net/MDD, selector counts vs prev, top-5 ranking, scrape coverage, auth days left)"
if [ "$DRY" = 0 ]; then
  COV="$(grep -E 'done|errors' "$SCRAPE_TMP" | tail -1)"
  MSG="$(COV="$COV" AUTH_LEFT="${AUTH_LEFT:-?}" python3 - <<'PY'
import csv, json, os
L = ["Stratzy weekly (almanac)"]
try:
    b = json.load(open("book_backtest.json")); c = b["combined"]
    L.append(f"Book {b['window']['start']}..{b['window']['end']}: net Rs{c['total_net']:,.0f}, MDD Rs{c['max_dd_net']:,.0f}")
except Exception as e: L.append(f"Book: n/a ({type(e).__name__})")
try:
    n = json.load(open("selector.json"))["counts"]
    try: p = json.load(open("/tmp/selector.prev.json"))["counts"]
    except Exception: p = {}
    d = lambda k: f"{n[k]} ({n[k]-p[k]:+d})" if k in p else str(n[k])
    L.append(f"Selector: deploy {d('deploy_eligible')}, copy {d('copy_eligible')}, algos {n['algos']}")
except Exception as e: L.append(f"Selector: n/a ({type(e).__name__})")
try:
    rows = list(csv.DictReader(open("research/ranking.csv")))[:5]
    L.append("Top 5: " + "; ".join(f"{r['rank_composite']}. {r['name']} (Rs{float(r['net_rs_12m']):,.0f})" for r in rows))
except Exception as e: L.append(f"Top 5: n/a ({type(e).__name__})")
L.append("Scrape: " + (os.environ.get("COV") or "no coverage line"))
L.append(f"Auth: {os.environ['AUTH_LEFT']} days left")
print("\n".join(L))
PY
)"
  tg "$MSG"
fi
rm -f "$SCRAPE_TMP"
ts "done"
