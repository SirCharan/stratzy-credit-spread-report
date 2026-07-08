#!/usr/bin/env bash
# Stratzy Almanac — DAILY refresh (numbers only, no auth needed).
# Refreshes the public-API pages (movers + universe), commits, deploys, and pushes a concise
# @pookie digest. The deep per-trade pages (equity curves, per-algo P&L, AI insight) are NOT
# touched here — they refresh weekly via refresh_weekly.sh (needs a DHAN Chrome login).
# Runs unattended from launchd. Fails loud but never force-pushes.
set -uo pipefail

REPO="$HOME/stratzy-credit-spread-report"
ENV_FILE="$HOME/claude/lakshmi/.env"
LOG="$REPO/insights/refresh_daily.log"
TEAM="team_QUgI2tENi0Wo8L7m2s2GoATi"

cd "$REPO" || { echo "no repo"; exit 1; }
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "===== $(date '+%F %T') daily refresh ====="

# 1. sync (never clobber; the publisher/other agents may have pushed)
git pull --rebase --autostash origin main || { echo "git pull failed"; exit 1; }

# 2. public-API regen (no auth)
python3 generate_movers.py   || { echo "movers gen failed"; exit 1; }
python3 generate_universe.py || { echo "universe gen failed"; exit 1; }

# 3. commit + push only if something changed
if ! git diff --quiet -- movers universe.json; then
  git add movers universe.json
  git commit -m "Movers+universe: daily $(date '+%F') numbers" || true
  git push origin main || { echo "push failed"; exit 1; }
  echo "pushed"
else
  echo "no data change"
fi

# 4. deploy (git auto-deploy is unreliable for this project → explicit CLI deploy)
VT="$(grep -m1 '^VERCEL_TOKEN_CKDELTA=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'\'' ')"
if [ -n "$VT" ]; then
  vercel --prod --yes --token "$VT" --scope "$TEAM" >/dev/null && echo "deployed" || echo "deploy failed"
else
  echo "no VERCEL_TOKEN_CKDELTA — skipped deploy"
fi

# 5. optional @pookie digest (concise; full detail via the interactive /movers command).
#    Set STRATZY_TG_BOT_TOKEN + STRATZY_TG_CHAT_ID in the env file to enable.
BT="$(grep -m1 '^STRATZY_TG_BOT_TOKEN=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'\'' ')"
CH="$(grep -m1 '^STRATZY_TG_CHAT_ID=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'\'' ')"
if [ -n "$BT" ] && [ -n "$CH" ]; then
  MSG="$(python3 - <<'PY'
import json
d = json.load(open("movers/latest.json"))
db = d.get("day_board") or {}; wb = d.get("week_board") or {}; p = d.get("portfolio") or {}
def lead(b, k):
    ls = (b or {}).get("leaders") or []
    return f"{ls[0]['name']} {ls[0].get(k):+.1f}%" if ls else "—"
lines = ["\U0001F4CA Stratzy daily — " + d.get("generated_at","")]
lines.append(f"1D: {lead(db,'day_pnl')}")
lines.append(f"1W: {lead(wb,'seven_day_pnl')}")
if p: lines.append(f"Book 1M {p.get('weighted_1m')}%" + (f" · {len(p.get('flags') or [])} slipping" if p.get('flags') else ""))
lines.append("Full detail: /movers")
print("\n".join(lines))
PY
)"
  curl -s -X POST "https://api.telegram.org/bot${BT}/sendMessage" \
    --data-urlencode "chat_id=${CH}" --data-urlencode "text=${MSG}" >/dev/null \
    && echo "digest sent" || echo "digest failed"
else
  echo "no STRATZY_TG_* — skipped digest"
fi
echo "done $(date '+%T')"
