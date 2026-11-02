"""READ-ONLY Stratzy auth probe. Never writes files, never calls scraper mint(), never logs in.

Mints an in-memory accessToken via signalPositionsV2 (refreshToken cookie), then does
ONE pastAdvices GET. Prints statuses and counts only, never token values.
"""

import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
COOKIES = ROOT / "data" / "stratzy_cookies.json"
BASE = "https://stratzy.in"
ADVISOR = "687d0a309107a80e07401e5d"  # IV-Imbalance
DATE = "2026-10-30"
HEAD = {
    "Origin": BASE,
    "Referer": BASE + "/",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0 Safari/537.36",
}


def main() -> int:
    cookies = json.loads(COOKIES.read_text())  # read-only
    s = requests.Session()
    s.headers.update(HEAD)
    for k, v in cookies.items():
        s.cookies.set(k, v, domain=".stratzy.in")

    r1 = s.get(f"{BASE}/api/mobile/signalPositionsV2", timeout=20)
    minted = s.cookies.get("accessToken") or r1.cookies.get("accessToken")
    print(f"signalPositionsV2 http={r1.status_code} accessToken_set={bool(minted)}", flush=True)
    if minted:
        s.cookies.set("accessToken", minted, domain=".stratzy.in")

    r2 = s.get(
        f"{BASE}/api/web/pastAdvices",
        params={"advisorId": ADVISOR, "date": DATE},
        timeout=30,
    )
    count = "n/a"
    is_json = False
    try:
        body = r2.json()
        is_json = True
        if isinstance(body, dict) and isinstance(body.get("pastAdvices"), list):
            count = len(body["pastAdvices"])
        elif isinstance(body, list):
            count = len(body)
    except ValueError:
        pass
    print(f"pastAdvices http={r2.status_code} json={is_json} advices={count}", flush=True)
    ok = r2.status_code == 200 and is_json
    print("MINT_OK" if ok else "MINT_DEAD", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
