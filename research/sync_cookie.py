"""Sync the Stratzy refreshToken from the grokbot session into data/stratzy_cookies.json.

Reads STRATZY_COOKIE from ~/claude/stratzygrokbot/session.env, decodes the JWT exp (no deps),
prints days left, replaces the almanac token only if the bot's exp is later (file mode 600).
Default: sync + one mint probe (research/probe_auth.py); MINT_DEAD -> exit 2.
--check: token check only (no writes, no network). Never prints token values.
"""

import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COOKIES = ROOT / "data" / "stratzy_cookies.json"
SESSION_ENV = Path.home() / "claude" / "stratzygrokbot" / "session.env"


def jwt_exp(tok: str) -> int:
    try:
        p = tok.split(".")[1]
        return int(json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))["exp"])
    except Exception:
        return 0


def bot_token() -> str:
    try:
        for line in SESSION_ENV.read_text().splitlines():
            if line.startswith("STRATZY_COOKIE="):
                m = re.search(r"refreshToken=([^;\"'\s]+)", line)
                return m.group(1) if m else ""
    except OSError:
        pass
    return ""


def days(exp: int) -> float:
    return (exp - time.time()) / 86400


def main() -> int:
    check = "--check" in sys.argv
    bot = bot_token()
    try:
        mine = json.loads(COOKIES.read_text())
    except (OSError, ValueError):
        mine = {}
    be, me = jwt_exp(bot), jwt_exp(mine.get("refreshToken", ""))
    print(f"bot_refreshToken days_left={days(be):.1f}" if be else "bot_refreshToken missing/undecodable")
    print(f"almanac_refreshToken days_left={days(me):.1f}" if me else "almanac_refreshToken missing/undecodable")
    best = max(be, me)
    print(f"days_left={days(best):.1f}" if best else "days_left=0")
    if check:
        return 0
    if be > me:
        mine["refreshToken"] = bot
        COOKIES.parent.mkdir(exist_ok=True)
        fd = os.open(COOKIES, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(mine, f)
        os.chmod(COOKIES, 0o600)
        print("replaced almanac refreshToken with the bot's (later exp)")
    out = subprocess.run(
        [sys.executable, str(ROOT / "research" / "probe_auth.py")], capture_output=True, text=True
    ).stdout
    print(out.strip())
    if "MINT_OK" not in out:
        print("auth dead: log in + capture_session.py")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
