#!/usr/bin/env python3
"""fetch_market_data.py — NIFTY 50 + India VIX daily series with regime tags.

Pulls 2 years of NIFTY 50 (^NSEI) daily OHLC and India VIX (^INDIAVIX) close
via yfinance, merges them on date, and derives the same fields the site's
regime classifier (assets/js/regime.js) uses so downstream code agrees with
the SPA:

    ret_1d       — fractional daily NIFTY close-to-close return (0.01 = 1%)
    vix          — India VIX close
    vix_chg_5d   — fractional 5-trading-day change in VIX ((vix/vix[-5])-1)
    trend_20d    — "bull" | "side" | "bear", same rule as regime.js:
                   20-day trailing close return >= +2% -> bull,
                   <= -2% -> bear, else side. (regime.js calls the middle
                   bucket "sideways"; this script uses "side" per spec.)
    rv_20d       — 20-day trailing realized vol, annualised (stdev * sqrt(252)),
                   population stdev (n divisor) to match regime.js's stdev().

If yfinance's ^INDIAVIX pull fails (empty/errors), falls back to NSE's
historical VIX CSV archive.

Output: nifty_vix_daily.json at the repo root —
    [{date, open, high, low, close, ret_1d, vix, vix_chg_5d, trend_20d, rv_20d}, ...]
sorted ascending by date. Rows are dropped only if NIFTY OHLC is missing;
missing VIX for a given date is left as null (rare, e.g. brand-new exchange
holidays on one series but not the other).

Usage:
    python3 fetch_market_data.py [--years 2] [--out nifty_vix_daily.json]

No args required. No secrets involved (public market data only).
"""

import argparse
import io
import json
import math
import sys
import urllib.request
from datetime import datetime, timedelta

DIR_WINDOW = 20
DIR_BULL = 2.0
DIR_BEAR = -2.0
VOL_WINDOW = 20
ANN = math.sqrt(252)

NSE_VIX_CSV_URLS = [
    "https://nsearchives.nseindia.com/content/vix/vixhistory.csv",
    "https://archives.nseindia.com/content/vix/vixhistory.csv",
]
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def stdev_pop(values):
    """Population stdev (n divisor), matching regime.js's stdev()."""
    n = len(values)
    if n < 2:
        return 0.0
    m = sum(values) / n
    return math.sqrt(sum((v - m) ** 2 for v in values) / n)


def fetch_nifty(years):
    import yfinance as yf

    end = datetime.today()
    start = end - timedelta(days=int(years * 365.25) + 10)
    df = yf.download(
        "^NSEI",
        start=start.date().isoformat(),
        end=None,
        progress=False,
        auto_adjust=False,
    )
    if df is None or df.empty:
        raise SystemExit("yfinance returned no data for ^NSEI")
    if (
        isinstance(df.columns, type(df.columns))
        and hasattr(df.columns, "nlevels")
        and df.columns.nlevels > 1
    ):
        # MultiIndex columns (Price, Ticker) — flatten to the single ticker.
        df.columns = [c[0] for c in df.columns]
    df = df[["Open", "High", "Low", "Close"]].dropna()
    out = {}
    for ts, row in df.iterrows():
        d = ts.strftime("%Y-%m-%d")
        out[d] = {
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
        }
    return out


def fetch_vix_yfinance(years):
    import yfinance as yf

    end = datetime.today()
    start = end - timedelta(days=int(years * 365.25) + 10)
    df = yf.download(
        "^INDIAVIX",
        start=start.date().isoformat(),
        end=None,
        progress=False,
        auto_adjust=False,
    )
    if df is None or df.empty:
        return {}
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = [c[0] for c in df.columns]
    df = df[["Close"]].dropna()
    out = {}
    for ts, row in df.iterrows():
        d = ts.strftime("%Y-%m-%d")
        out[d] = round(float(row["Close"]), 4)
    return out


def fetch_vix_nse_fallback(years):
    """NSE historical VIX CSV archive, tried when yfinance's ^INDIAVIX fails."""
    cutoff = (datetime.today() - timedelta(days=int(years * 365.25) + 10)).date()
    last_err = None
    for url in NSE_VIX_CSV_URLS:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "*/*"}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
            text = raw.decode("utf-8", errors="replace")
            if "<html" in text.lower()[:200]:
                raise ValueError("got an HTML error page, not a CSV")
            out = {}
            lines = text.strip().splitlines()
            header = [h.strip().lower() for h in lines[0].split(",")]
            date_idx = next(i for i, h in enumerate(header) if "date" in h)
            close_idx = next(i for i, h in enumerate(header) if "close" in h)
            for line in lines[1:]:
                parts = line.split(",")
                if len(parts) <= max(date_idx, close_idx):
                    continue
                raw_date = parts[date_idx].strip()
                try:
                    dt = datetime.strptime(raw_date, "%d-%b-%Y").date()
                except ValueError:
                    try:
                        dt = datetime.strptime(raw_date, "%d-%m-%Y").date()
                    except ValueError:
                        continue
                if dt < cutoff:
                    continue
                try:
                    out[dt.isoformat()] = round(float(parts[close_idx].strip()), 4)
                except ValueError:
                    continue
            if out:
                return out
        except Exception as e:  # noqa: BLE001 - fallback path, try next URL
            last_err = e
            continue
    print(f"[fetch_market_data] NSE VIX fallback failed: {last_err}", file=sys.stderr)
    return {}


def build_rows(nifty, vix):
    dates = sorted(nifty.keys())
    closes = [nifty[d]["close"] for d in dates]
    rets = [
        0.0 if i == 0 else closes[i] / closes[i - 1] - 1 for i in range(len(closes))
    ]

    rows = []
    for i, d in enumerate(dates):
        trend = "side"
        if i >= DIR_WINDOW:
            chg = (closes[i] / closes[i - DIR_WINDOW] - 1) * 100
            trend = "bull" if chg >= DIR_BULL else "bear" if chg <= DIR_BEAR else "side"
        rv = None
        if i >= VOL_WINDOW:
            window = rets[i - VOL_WINDOW + 1 : i + 1]
            rv = round(stdev_pop(window) * ANN, 6)

        vix_close = vix.get(d)
        vix_chg_5d = None
        if vix_close is not None and i >= 5:
            d5 = dates[i - 5]
            vix5 = vix.get(d5)
            if vix5:
                vix_chg_5d = round(vix_close / vix5 - 1, 6)

        rows.append(
            {
                "date": d,
                "open": nifty[d]["open"],
                "high": nifty[d]["high"],
                "low": nifty[d]["low"],
                "close": nifty[d]["close"],
                "ret_1d": round(rets[i], 6),
                "vix": vix_close,
                "vix_chg_5d": vix_chg_5d,
                "trend_20d": trend,
                "rv_20d": rv,
            }
        )
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Fetch NIFTY 50 + India VIX daily series -> nifty_vix_daily.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--years", type=float, default=2.0, help="lookback window in years (default 2)"
    )
    parser.add_argument(
        "--out",
        default="nifty_vix_daily.json",
        help="output path (default ./nifty_vix_daily.json)",
    )
    args = parser.parse_args()

    print(f"[fetch_market_data] fetching ^NSEI ({args.years}y)...")
    nifty = fetch_nifty(args.years)
    print(f"[fetch_market_data] NIFTY rows: {len(nifty)}")

    print("[fetch_market_data] fetching ^INDIAVIX via yfinance...")
    vix = fetch_vix_yfinance(args.years)
    if not vix:
        print("[fetch_market_data] yfinance VIX empty, trying NSE CSV fallback...")
        vix = fetch_vix_nse_fallback(args.years)
    print(f"[fetch_market_data] VIX rows: {len(vix)}")

    rows = build_rows(nifty, vix)
    with open(args.out, "w") as f:
        json.dump(rows, f, indent=None, separators=(",", ":"))

    missing_vix = sum(1 for r in rows if r["vix"] is None)
    print(f"[fetch_market_data] wrote {len(rows)} rows -> {args.out}")
    print(f"[fetch_market_data] date range: {rows[0]['date']} .. {rows[-1]['date']}")
    print(f"[fetch_market_data] rows missing VIX: {missing_vix}")
    trend_counts = {}
    for r in rows:
        trend_counts[r["trend_20d"]] = trend_counts.get(r["trend_20d"], 0) + 1
    print(f"[fetch_market_data] trend_20d distribution: {trend_counts}")


if __name__ == "__main__":
    main()
