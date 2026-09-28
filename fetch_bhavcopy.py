#!/usr/bin/env python3
"""fetch_bhavcopy.py — NIFTY option-chain IV series from NSE F&O UDiFF bhavcopy.

For each NSE trading weekday in the last N days (default 365), downloads the
NSE F&O UDiFF bhavcopy zip:

    https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip

(a browser User-Agent is required; weekends/holidays 404 and are skipped;
network requests are throttled to 1/s; zips are cached under data/bhav/ so
re-runs only fetch new days).

From that day's NIFTY index options (FinInstrmTp == "IDO", TckrSymb ==
"NIFTY"), picks the nearest expiry with dte >= 0; if that expiry's dte < 1
(same-day expiry, whose ATM IV is numerically unstable into the close), the
next expiry is used instead. It then computes, via Black-Scholes with a
bisection implied-vol solver (r = 6.5%, no scipy):

    atm_iv       — average of ATM call + put implied vol at the strike
                   nearest the spot price
    put_otm_iv   — implied vol of the put with strike nearest spot * 0.98
    call_otm_iv  — implied vol of the call with strike nearest spot * 1.02
    skew         — put_otm_iv - call_otm_iv
    iv_rank_252  — percentile rank (0-100) of atm_iv within the trailing
                   window of up to 252 prior trading days actually computed
                   so far (expands from 1 day at the start of the series)

Spot price is read from the bhavcopy's UndrlygPric column (median across
that expiry's rows); if that's missing/zero, falls back to the matching
date's `close` in nifty_vix_daily.json (run fetch_market_data.py first for
that fallback to have data).

Output: iv_daily.json at the repo root —
    [{date, expiry, dte, spot, atm_strike, atm_iv, put_otm_iv, call_otm_iv,
      skew, iv_rank}, ...]
sorted ascending by date. Days with no usable NIFTY option data (holiday,
404, no liquid ATM quotes) are skipped, not padded with nulls.

Usage:
    python3 fetch_bhavcopy.py [--days 365] [--cache-dir data/bhav]
                               [--nifty-json nifty_vix_daily.json]
                               [--out iv_daily.json] [--rate 1.0]

No secrets involved (public NSE market data only).
"""

import argparse
import io
import json
import math
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta

import pandas as pd

BHAV_URL_TMPL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
RISK_FREE = 0.065


# ---------- Black-Scholes + bisection IV (no scipy) ----------


def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(S, K, T, r, sigma, is_call):
    if T <= 0 or sigma <= 0:
        intrinsic = max(0.0, S - K) if is_call else max(0.0, K - S)
        return intrinsic
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    if is_call:
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def implied_vol_bisect(
    price, S, K, T, r, is_call, lo=1e-4, hi=5.0, tol=1e-5, max_iter=100
):
    """Bisection IV solver. Returns None if price is outside the no-arbitrage
    bounds spanned by [lo, hi] or T/price are unusable."""
    if T <= 0 or price <= 0:
        return None
    intrinsic = max(0.0, S - K) if is_call else max(0.0, K - S)
    if price < intrinsic - 1e-6:
        return None
    f_lo = bs_price(S, K, T, r, lo, is_call) - price
    f_hi = bs_price(S, K, T, r, hi, is_call) - price
    if f_lo > 0 or f_hi < 0:
        return None  # price outside range spanned by sigma in [lo, hi]
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        f_mid = bs_price(S, K, T, r, mid, is_call) - price
        if abs(f_mid) < tol:
            return mid
        if f_mid > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


# ---------- bhavcopy download / cache ----------


def download_bhav(d: date, cache_dir: str, rate_sleep: float):
    ymd = d.strftime("%Y%m%d")
    cache_path = f"{cache_dir}/BhavCopy_NSE_FO_{ymd}.csv.zip"
    try:
        with open(cache_path, "rb") as f:
            return f.read(), True
    except FileNotFoundError:
        pass

    url = BHAV_URL_TMPL.format(ymd=ymd)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, False
        raise
    except urllib.error.URLError:
        return None, False
    finally:
        time.sleep(rate_sleep)

    with open(cache_path, "wb") as f:
        f.write(data)
    return data, False


def parse_nifty_options(zip_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            return None
        with zf.open(names[0]) as f:
            df = pd.read_csv(f, low_memory=False)
    sub = df[(df["TckrSymb"] == "NIFTY") & (df["FinInstrmTp"] == "IDO")].copy()
    if sub.empty:
        return None
    return sub


# ---------- per-day IV computation ----------


def pick_expiry(sub: pd.DataFrame, trade_dt: date):
    expiries = sorted(
        datetime.strptime(x, "%Y-%m-%d").date() for x in sub["XpryDt"].unique()
    )
    candidates = [e for e in expiries if (e - trade_dt).days >= 0]
    if not candidates:
        return None, None
    expiry = candidates[0]
    dte = (expiry - trade_dt).days
    if dte < 1 and len(candidates) > 1:
        expiry = candidates[1]
        dte = (expiry - trade_dt).days
    return expiry, dte


def option_price(row):
    for col in ("ClsPric", "SttlmPric", "LastPric"):
        v = row.get(col)
        if v is not None and not pd.isna(v) and float(v) > 0:
            return float(v)
    return None


def compute_day(sub: pd.DataFrame, trade_dt: date, fallback_spot):
    expiry, dte = pick_expiry(sub, trade_dt)
    if expiry is None:
        return None
    chain = sub[sub["XpryDt"] == expiry.isoformat()]
    if chain.empty:
        return None

    spot = None
    und = chain["UndrlygPric"].dropna()
    und = und[und > 0]
    if not und.empty:
        spot = float(und.median())
    if not spot and fallback_spot:
        spot = fallback_spot
    if not spot:
        return None

    # Same-day-fraction: NSE options expire ~15:30 IST; bhavcopy is EOD (~15:30)
    # settlement data, so a genuine same-day (dte==0) row would have ~zero time
    # left. pick_expiry() already routes dte<1 to the next expiry, so this is
    # just a floor to keep T > 0 for the bisection solver.
    T = max(dte, 0) / 365.0
    if T <= 0:
        T = (1.0 / 24) / 365.0  # 1-hour floor, degenerate case only

    strikes = sorted(chain["StrkPric"].dropna().unique())
    if not strikes:
        return None

    by_strike_call = {}
    by_strike_put = {}
    for _, row in chain.iterrows():
        k = float(row["StrkPric"])
        px = option_price(row)
        if px is None:
            continue
        if row["OptnTp"] == "CE":
            by_strike_call[k] = px
        elif row["OptnTp"] == "PE":
            by_strike_put[k] = px

    def nearest_strike(target, pool):
        if not pool:
            return None
        return min(pool.keys(), key=lambda k: abs(k - target))

    atm_k = nearest_strike(spot, {k: 1 for k in strikes})
    if atm_k is None:
        return None

    atm_call_iv = (
        implied_vol_bisect(by_strike_call.get(atm_k), spot, atm_k, T, RISK_FREE, True)
        if atm_k in by_strike_call
        else None
    )
    atm_put_iv = (
        implied_vol_bisect(by_strike_put.get(atm_k), spot, atm_k, T, RISK_FREE, False)
        if atm_k in by_strike_put
        else None
    )
    ivs = [v for v in (atm_call_iv, atm_put_iv) if v is not None]
    if not ivs:
        return None
    atm_iv = sum(ivs) / len(ivs)

    put_k = nearest_strike(spot * 0.98, by_strike_put)
    put_otm_iv = (
        implied_vol_bisect(by_strike_put[put_k], spot, put_k, T, RISK_FREE, False)
        if put_k is not None
        else None
    )

    call_k = nearest_strike(spot * 1.02, by_strike_call)
    call_otm_iv = (
        implied_vol_bisect(by_strike_call[call_k], spot, call_k, T, RISK_FREE, True)
        if call_k is not None
        else None
    )

    skew = (
        (put_otm_iv - call_otm_iv)
        if (put_otm_iv is not None and call_otm_iv is not None)
        else None
    )

    return {
        "date": trade_dt.isoformat(),
        "expiry": expiry.isoformat(),
        "dte": dte,
        "spot": round(spot, 2),
        "atm_strike": atm_k,
        "atm_iv": round(atm_iv, 6),
        "put_otm_iv": round(put_otm_iv, 6) if put_otm_iv is not None else None,
        "call_otm_iv": round(call_otm_iv, 6) if call_otm_iv is not None else None,
        "skew": round(skew, 6) if skew is not None else None,
    }


def add_iv_rank(rows, window=252):
    atm = [r["atm_iv"] for r in rows]
    for i, r in enumerate(rows):
        lo = max(0, i - window + 1)
        hist = atm[lo : i + 1]
        n = len(hist)
        if n < 2:
            r["iv_rank"] = 50.0
            continue
        cur = hist[-1]
        rank = (
            sum(1 for v in hist if v <= cur) - 1
        )  # exclude self double count baseline
        r["iv_rank"] = round(100.0 * rank / (n - 1), 2)
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Fetch NSE F&O bhavcopy -> NIFTY ATM IV / skew series -> iv_daily.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="lookback window in calendar days (default 365)",
    )
    parser.add_argument(
        "--cache-dir",
        default="data/bhav",
        help="zip cache directory (default data/bhav)",
    )
    parser.add_argument(
        "--nifty-json", default="nifty_vix_daily.json", help="fallback spot source"
    )
    parser.add_argument(
        "--out", default="iv_daily.json", help="output path (default ./iv_daily.json)"
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=1.0,
        help="seconds between network requests (default 1.0)",
    )
    args = parser.parse_args()

    import os

    os.makedirs(args.cache_dir, exist_ok=True)

    fallback_close = {}
    try:
        with open(args.nifty_json) as f:
            for row in json.load(f):
                fallback_close[row["date"]] = row["close"]
    except FileNotFoundError:
        print(
            f"[fetch_bhavcopy] {args.nifty_json} not found, no spot fallback available",
            file=sys.stderr,
        )

    end = date.today()
    start = end - timedelta(days=args.days)
    all_days = []
    d = start
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri only; weekends 404 anyway but skip the request
            all_days.append(d)
        d += timedelta(days=1)

    print(f"[fetch_bhavcopy] scanning {len(all_days)} weekdays from {start} to {end}")

    rows = []
    n_404 = 0
    n_cached = 0
    n_downloaded = 0
    n_no_data = 0
    for i, d in enumerate(all_days):
        data, was_cached = download_bhav(d, args.cache_dir, args.rate)
        if data is None:
            n_404 += 1
            continue
        if was_cached:
            n_cached += 1
        else:
            n_downloaded += 1
        sub = parse_nifty_options(data)
        if sub is None:
            n_no_data += 1
            continue
        row = compute_day(sub, d, fallback_close.get(d.isoformat()))
        if row is None:
            n_no_data += 1
            continue
        rows.append(row)
        if (i + 1) % 25 == 0:
            print(
                f"[fetch_bhavcopy] {i + 1}/{len(all_days)} scanned, {len(rows)} usable rows so far"
            )

    rows.sort(key=lambda r: r["date"])
    add_iv_rank(rows)

    with open(args.out, "w") as f:
        json.dump(rows, f, indent=None, separators=(",", ":"))

    print(
        f"[fetch_bhavcopy] weekdays scanned: {len(all_days)}  cached-hits: {n_cached}  downloaded: {n_downloaded}  404/holiday: {n_404}  no-usable-data: {n_no_data}"
    )
    print(f"[fetch_bhavcopy] wrote {len(rows)} rows -> {args.out}")
    if rows:
        print(f"[fetch_bhavcopy] date range: {rows[0]['date']} .. {rows[-1]['date']}")

    # Sanity: ATM IV should track India VIX.
    if rows and fallback_close:
        try:
            with open(args.nifty_json) as f:
                vix_by_date = {
                    r["date"]: r["vix"]
                    for r in json.load(f)
                    if r.get("vix") is not None
                }
            paired = [
                (r["atm_iv"] * 100, vix_by_date[r["date"]])
                for r in rows
                if r["date"] in vix_by_date
            ]
            if len(paired) >= 5:
                xs = [p[0] for p in paired]
                ys = [p[1] for p in paired]
                n = len(xs)
                mx, my = sum(xs) / n, sum(ys) / n
                cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
                sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
                sy = math.sqrt(sum((y - my) ** 2 for y in ys))
                corr = cov / (sx * sy) if sx > 0 and sy > 0 else float("nan")
                print(
                    f"[fetch_bhavcopy] corr(atm_iv%, India VIX) over {n} matched days: {corr:.4f}"
                )
            else:
                print(
                    f"[fetch_bhavcopy] too few matched days ({len(paired)}) to compute correlation"
                )
        except Exception as e:  # noqa: BLE001
            print(f"[fetch_bhavcopy] correlation check failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
