#!/usr/bin/env python3
"""fetch_dhan_intraday.py — Dhan v2 historical charts puller (index + expired weekly options).

Fetches, for the last N days (default 365):
  1. NIFTY 50 index 5-minute OHLC bars, via POST /v2/charts/intraday, chunked
     into <=90-day windows (the API's per-request limit).
  2. Expired NIFTY weekly option 5-minute bars (ATM-3..ATM+3, CALL+PUT), via
     POST /v2/charts/rollingoption, chunked into <=30-day windows (the API's
     per-request limit for this endpoint), one request per (strike, option
     type) pair per chunk.

Credentials: read from ~/stratzygrokbot/dhan.env (DHAN_CLIENT_ID,
DHAN_ACCESS_TOKEN — shell `KEY=value` lines, `export` prefix tolerated).
Never printed or logged — only their lengths are shown, to confirm they
loaded.

Read-only: only ever issues the two GET-shaped chart POSTs above against
Dhan's public charts API. Places no orders, touches no order/trade endpoints.

Output: two CSVs written to --out-dir (default ~/dhan-hist):
    nifty_5m.csv     — timestamp, open, high, low, close, volume
    rolling_opt.csv  — timestamp, strike_offset, option_type, open, high,
                        low, close, volume, oi, iv, spot

Usage:
    python3 fetch_dhan_intraday.py [--days 365] [--out-dir ~/dhan-hist]
                                    [--env ~/stratzygrokbot/dhan.env]
                                    [--skip-index] [--skip-options]
                                    [--rate 1.0]

Exit codes: 0 ok (even if some chunks failed — see summary printed at end
and the *_errors.log files in --out-dir); 1 missing/unreadable credentials
or unrecoverable HTTP auth failure (401/403).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://api.dhan.co/v2"
NIFTY_SECURITY_ID = "13"

STRIKE_OFFSETS = [f"ATM{s:+d}" if s != 0 else "ATM" for s in range(-3, 4)]
OPTION_TYPES = ["CALL", "PUT"]
REQUIRED_DATA = ["open", "high", "low", "close", "iv", "volume", "oi", "spot"]


def load_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SystemExit(f"credentials file not found: {path}")
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def date_chunks(start: dt.date, end: dt.date, chunk_days: int):
    """Yield (chunk_start, chunk_end) inclusive date pairs covering [start, end]."""
    cur = start
    while cur <= end:
        chunk_end = min(cur + dt.timedelta(days=chunk_days - 1), end)
        yield cur, chunk_end
        cur = chunk_end + dt.timedelta(days=1)


class DhanClient:
    def __init__(self, client_id: str, access_token: str, rate: float):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "access-token": access_token,
                "client-id": client_id,
            }
        )
        self.min_interval = 1.0 / rate if rate > 0 else 0.0
        self._last_call = 0.0

    def _throttle(self):
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def post(self, path: str, body: dict, max_retries: int = 5) -> dict | None:
        url = f"{BASE_URL}{path}"
        backoff = 2.0
        for attempt in range(1, max_retries + 1):
            self._throttle()
            self._last_call = time.monotonic()
            try:
                resp = self.session.post(url, json=body, timeout=30)
            except requests.RequestException as e:
                print(
                    f"    [network error] {e} (attempt {attempt}/{max_retries})",
                    file=sys.stderr,
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403):
                print(
                    f"    [AUTH FAILURE {resp.status_code}] {resp.text[:300]}",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            if resp.status_code == 429:
                print(
                    f"    [429 rate-limited] backing off {backoff:.1f}s (attempt {attempt}/{max_retries})",
                    file=sys.stderr,
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            print(
                f"    [HTTP {resp.status_code}] {resp.text[:300]} (attempt {attempt}/{max_retries})",
                file=sys.stderr,
            )
            time.sleep(backoff)
            backoff *= 2
        print(f"    [GAVE UP] {path} body={body}", file=sys.stderr)
        return None


def fetch_index(client: DhanClient, days: int, out_dir: Path) -> int:
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    rows_written = 0
    out_path = out_dir / "nifty_5m.csv"
    err_path = out_dir / "nifty_5m_errors.log"
    with out_path.open("w", newline="") as f, err_path.open("w") as errf:
        w = csv.writer(f)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c_start, c_end in date_chunks(start, end, 90):
            body = {
                "securityId": NIFTY_SECURITY_ID,
                "exchangeSegment": "IDX_I",
                "instrument": "INDEX",
                "interval": "5",
                "oi": False,
                "fromDate": f"{c_start.isoformat()} 09:15:00",
                "toDate": f"{c_end.isoformat()} 15:30:00",
            }
            print(f"  [index] {c_start} .. {c_end}")
            data = client.post("/charts/intraday", body)
            if not data or "timestamp" not in data:
                errf.write(f"{c_start},{c_end},NO_DATA,{data}\n")
                continue
            n = len(data.get("timestamp", []))
            for i in range(n):
                w.writerow(
                    [
                        data["timestamp"][i],
                        data.get("open", [None] * n)[i],
                        data.get("high", [None] * n)[i],
                        data.get("low", [None] * n)[i],
                        data.get("close", [None] * n)[i],
                        data.get("volume", [None] * n)[i],
                    ]
                )
            rows_written += n
    return rows_written


def fetch_options(client: DhanClient, days: int, out_dir: Path) -> int:
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    rows_written = 0
    out_path = out_dir / "rolling_opt.csv"
    err_path = out_dir / "rolling_opt_errors.log"
    iv_seen = False
    with out_path.open("w", newline="") as f, err_path.open("w") as errf:
        w = csv.writer(f)
        w.writerow(
            [
                "timestamp",
                "strike_offset",
                "option_type",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "oi",
                "iv",
                "spot",
                "strike",
            ]
        )
        chunks = list(date_chunks(start, end, 30))
        total = len(chunks) * len(STRIKE_OFFSETS) * len(OPTION_TYPES)
        done = 0
        for c_start, c_end in chunks:
            for strike in STRIKE_OFFSETS:
                for opt_type in OPTION_TYPES:
                    done += 1
                    body = {
                        "exchangeSegment": "NSE_FNO",
                        "interval": "5",
                        "securityId": NIFTY_SECURITY_ID,
                        "instrument": "OPTIDX",
                        "expiryFlag": "WEEK",
                        "expiryCode": 1,
                        "strike": strike,
                        "drvOptionType": opt_type,
                        "requiredData": REQUIRED_DATA,
                        "fromDate": c_start.isoformat(),
                        "toDate": c_end.isoformat(),
                    }
                    print(
                        f"  [opt {done}/{total}] {c_start}..{c_end} strike={strike} type={opt_type}"
                    )
                    resp = client.post("/charts/rollingoption", body)
                    if not resp:
                        errf.write(
                            f"{c_start},{c_end},{strike},{opt_type},NO_RESPONSE\n"
                        )
                        continue
                    leg = resp.get("data", resp)
                    side = (
                        leg.get("ce" if opt_type == "CALL" else "pe")
                        if isinstance(leg, dict)
                        else None
                    )
                    if side is None:
                        errf.write(
                            f"{c_start},{c_end},{strike},{opt_type},NULL_SIDE:{str(resp)[:200]}\n"
                        )
                        continue
                    ts_list = side.get("timestamp", [])
                    n = len(ts_list)
                    if n and side.get("iv"):
                        iv_seen = True
                    for i in range(n):

                        def g(key):
                            arr = side.get(key)
                            return arr[i] if arr and i < len(arr) else None

                        w.writerow(
                            [
                                ts_list[i],
                                strike,
                                opt_type,
                                g("open"),
                                g("high"),
                                g("low"),
                                g("close"),
                                g("volume"),
                                g("oi"),
                                g("iv"),
                                g("spot"),
                                g("strike"),
                            ]
                        )
                    rows_written += n
    print(f"  [opt] iv field populated in at least one response: {iv_seen}")
    return rows_written


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--out-dir", default=str(Path.home() / "dhan-hist"))
    p.add_argument("--env", default=str(Path.home() / "stratzygrokbot" / "dhan.env"))
    p.add_argument("--skip-index", action="store_true")
    p.add_argument("--skip-options", action="store_true")
    p.add_argument(
        "--rate", type=float, default=1.0, help="max requests/sec (default 1.0)"
    )
    args = p.parse_args()

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    env = load_env(Path(args.env).expanduser())
    client_id = env.get("DHAN_CLIENT_ID", "")
    access_token = env.get("DHAN_ACCESS_TOKEN", "")
    print(
        f"loaded credentials: DHAN_CLIENT_ID len={len(client_id)}, DHAN_ACCESS_TOKEN len={len(access_token)}"
    )
    if not client_id or not access_token:
        raise SystemExit("missing DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN in env file")

    client = DhanClient(client_id, access_token, args.rate)

    index_rows = 0
    opt_rows = 0
    if not args.skip_index:
        print(f"=== fetching NIFTY 50 index 5m bars, last {args.days}d ===")
        index_rows = fetch_index(client, args.days, out_dir)
    if not args.skip_options:
        print(
            f"=== fetching expired NIFTY weekly options 5m bars, last {args.days}d ==="
        )
        opt_rows = fetch_options(client, args.days, out_dir)

    print("=== summary ===")
    print(f"nifty_5m.csv rows: {index_rows} -> {out_dir / 'nifty_5m.csv'}")
    print(f"rolling_opt.csv rows: {opt_rows} -> {out_dir / 'rolling_opt.csv'}")


if __name__ == "__main__":
    main()
