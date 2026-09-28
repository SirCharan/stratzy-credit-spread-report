"""Scrape 1Y of Stratzy pastAdvices for every active option-strategy algo.

Cache: data/advices/<advisorId>/<iso-date>.json (one file per algo-day, resumable).
Auth: data/stratzy_cookies.json {refreshToken, accessToken} (gitignored, mode 600).
A 401 re-mints accessToken from refreshToken via signalPositionsV2; 3 consecutive
auth failures abort (exit 2). Never prints token values.

    python3 scrape_all_algos.py [--days 365] [--delay 0.4]
"""

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent
DATA = ROOT / "data"
CACHE = DATA / "advices"
COOKIES = DATA / "stratzy_cookies.json"
BASE = "https://stratzy.in"
HEAD = {
    "Origin": BASE,
    "Referer": BASE + "/",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0 Safari/537.36",
}
SKIP_CATS = {"Investing", "Swing", "Intraday"}


def iso(ddmmyyyy: str) -> str:
    d, m, y = ddmmyyyy.split("/")
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


def in_scope(a: dict) -> bool:
    return bool(a.get("isActive")) and (a.get("category") or "") not in SKIP_CATS


def mint(s: requests.Session) -> bool:
    r = s.get(f"{BASE}/api/mobile/signalPositionsV2", timeout=20)
    tok = s.cookies.get("accessToken")
    if r.ok and tok:
        c = json.loads(COOKIES.read_text())
        c["accessToken"] = tok
        COOKIES.write_text(json.dumps(c))
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--delay", type=float, default=0.4)
    a = ap.parse_args()

    s = requests.Session()
    s.headers.update(HEAD)
    for k, v in json.loads(COOKIES.read_text()).items():
        s.cookies.set(k, v, domain=".stratzy.in")

    algos = [
        x
        for x in s.get(f"{BASE}/api/web/algo/list", timeout=30).json()["data"]
        if in_scope(x)
    ]
    DATA.mkdir(exist_ok=True)
    (DATA / "algo_list.json").write_text(json.dumps(algos))
    cutoff = (dt.date.today() - dt.timedelta(days=a.days)).isoformat()
    jobs = [
        (x["_id"], x["name"], d)
        for x in algos
        for d in sorted({iso(k) for k in (x.get("performance") or {})})
        if d >= cutoff
    ]
    todo = [j for j in jobs if not (CACHE / j[0] / f"{j[2]}.json").exists()]
    print(
        f"{len(algos)} algos, {len(jobs)} algo-days, {len(todo)} to fetch", flush=True
    )

    auth_fail = errors = 0
    for i, (aid, name, d) in enumerate(todo, 1):
        try:
            r = s.get(
                f"{BASE}/api/web/pastAdvices",
                params={"advisorId": aid, "date": d},
                timeout=30,
            )
        except requests.RequestException as e:
            errors += 1
            print(f"net error {name} {d}: {type(e).__name__}", flush=True)
            time.sleep(5)
            continue
        if r.status_code in (401, 403):
            auth_fail += 1
            if auth_fail >= 3 or not mint(s):
                print(
                    f"ABORT: auth failed http={r.status_code} at {i}/{len(todo)}",
                    flush=True,
                )
                return 2
            continue
        auth_fail = 0
        if r.status_code == 429:
            time.sleep(30)
            continue
        if not r.ok:
            errors += 1
            continue
        out = CACHE / aid / f"{d}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(r.json().get("pastAdvices") or []))
        if i % 100 == 0:
            print(f"{i}/{len(todo)} done, {errors} errors", flush=True)
        time.sleep(a.delay)

    done = sum(1 for j in jobs if (CACHE / j[0] / f"{j[2]}.json").exists())
    print(
        f"DONE coverage {done}/{len(jobs)} = {done / max(len(jobs), 1):.1%}, errors {errors}",
        flush=True,
    )
    return 0 if done / max(len(jobs), 1) >= 0.98 else 1


if __name__ == "__main__":
    sys.exit(main())
