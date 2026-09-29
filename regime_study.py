#!/usr/bin/env python3
"""Regime study: join every closed advice (trade) to its market context AS OF ENTRY.

Reads the scrape cache directly (data/advices/<algoId>/<date>.json + data/algo_list.json),
not the /tmp-shaped all_*_advices.json bundles build_raw_from_cache.py produces for the
legacy report pipeline — those bucket algos by category name (lossy for a per-trade join
keyed on algo id). Algo universe = the 118 ids in explore_data.json (the vetted, deep-data
set the rest of the pipeline already committed to).

For every closed, non-backtest advice:
  - parses its legs' NIFTY/BANKNIFTY/SENSEX option symbols -> expiry, strike, CE/PE, side
  - classifies structure (credit_spread / straddle / strangle / condor / option_buy / other)
    and a directional bias score from the leg mix
  - computes P&L in premium points and Rs per 1 lot (using each leg's OWN `multiplier` field,
    not a static lot-size table — NIFTY's lot size changed twice inside this 1Y window, so a
    hardcoded dict silently mis-prices older trades; the source data already carries the
    correct multiplier per trade)
  - joins market context strictly AS OF THE PRIOR TRADING DAY close (never same-day: bhavcopy
    IV and the EOD-computed VIX/trend fields for day D are not known until after D's close, so
    using day D's own row for a trade entered during day D would be lookahead)
  - joins intraday NIFTY 5-min context (day-open, last-60-min momentum) and the rolling ATM IV
    nearest the entry timestamp, both of which ARE legitimately known at entry time

Output: regime_panel.json (repo root, served) + data/trades_enriched.parquet (every trade +
context, for later stages).

    python3 regime_study.py
"""

from __future__ import annotations

import bisect
import csv
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")

ADVICES_DIR = ROOT / "data" / "advices"
ALGO_LIST_PATH = ROOT / "data" / "algo_list.json"
EXPLORE_PATH = ROOT / "explore_data.json"
NIFTY_VIX_PATH = ROOT / "nifty_vix_daily.json"
IV_DAILY_PATH = ROOT / "iv_daily.json"
NIFTY_5M_PATH = ROOT / "data" / "dhan" / "nifty_5m.csv"
ROLLING_OPT_PATH = ROOT / "data" / "dhan" / "rolling_opt.csv"

OUT_PANEL = ROOT / "regime_panel.json"
OUT_TRADES_PARQUET = ROOT / "data" / "trades_enriched.parquet"
OUT_TRADES_CSV = ROOT / "data" / "trades_enriched.csv"

MIN_CELL_N = 10  # thin = n < this
MOMENTUM_FLAT_EPS = 0.0005  # +/-0.05% over 60min counted as flat, not a direction
VIX_CHG_FLAT_EPS = 0.01  # +/-1% 5d change counted as flat
SKEW_FLAT_EPS = 0.005

# fallback lot size, only used if a leg is missing its own `multiplier`
LOT_FALLBACK = {"NIFTY": 75, "BANKNIFTY": 30, "SENSEX": 20, "FINNIFTY": 25}

MONTH3 = {
    m: i + 1
    for i, m in enumerate(
        [
            "JAN",
            "FEB",
            "MAR",
            "APR",
            "MAY",
            "JUN",
            "JUL",
            "AUG",
            "SEP",
            "OCT",
            "NOV",
            "DEC",
        ]
    )
}
MONTH1 = {str(d): d for d in range(1, 10)} | {"O": 10, "N": 11, "D": 12}
UNDERLYINGS = ("BANKNIFTY", "FINNIFTY", "SENSEX", "NIFTY")  # longest-prefix-first


def load(path: Path):
    return json.loads(path.read_text())


def r2(v):
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, 4)


# ---------------------------------------------------------------------------
# symbol parsing
# ---------------------------------------------------------------------------

_RE_DMY = re.compile(
    r"^(\d{2})([A-Z]{3})(\d{2})(\d+)$"
)  # DD MON YY STRIKE (new unified fmt)
_RE_MY = re.compile(r"^(\d{2})([A-Z]{3})(\d+)$")  # YY MON STRIKE (old monthly, no day)
_RE_WEEKLY = re.compile(
    r"^(\d{2})([1-9OND])(\d{2})(\d+)$"
)  # YY M DD STRIKE (old weekly)


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(2000 + y if y < 100 else y, m, d)
    except ValueError:
        return None


def parse_symbol(symbol: str, entry_date: date) -> dict:
    """Best-effort parse of an NSE index-option symbol into underlying/strike/opt_type/expiry.

    Three symbol conventions appear in this cache across the 1Y window (NSE changed the
    format mid-year): DD+MON3+YY+STRIKE (new, unambiguous), YY+MON3+STRIKE (old monthly, no
    day), YY+<1-char month>+DD+STRIKE (old weekly). The three regexes overlap syntactically
    (a monthly string can spuriously full-match the weekly pattern's digit groups), so every
    pattern that matches is scored as a candidate and the one whose implied expiry date is
    closest to (and not much before) `entry_date` wins — a wrong split always implies either
    an impossible date or a wildly implausible strike.
    """
    s = (symbol or "").upper()
    underlying = "NIFTY"
    for u in UNDERLYINGS:
        if s.startswith(u):
            underlying = u
            s = s[len(u) :]
            break
    else:
        for u in UNDERLYINGS:
            if u in s:
                underlying = u
                break

    opt_type = None
    if s.endswith("CE") or s.endswith("PE"):
        opt_type = s[-2:]
        s = s[:-2]

    candidates = []
    m = _RE_DMY.match(s)
    if m:
        dd, mon, yy, strike = m.groups()
        if mon in MONTH3 and 1 <= int(dd) <= 31 and int(strike) >= 500:
            dt = _safe_date(int(yy), MONTH3[mon], int(dd))
            if dt:
                candidates.append((dt, int(strike)))
    m = _RE_MY.match(s)
    if m:
        yy, mon, strike = m.groups()
        if mon in MONTH3 and int(strike) >= 500:
            # no day in this format -> monthly expiry; approximate with month-end (only used
            # for the DTE bucket, which only distinguishes 0/1/2/3+ and monthlies always land
            # in 3+ regardless of the exact day).
            y = 2000 + int(yy)
            mo = MONTH3[mon]
            last_day = (date(y + (mo == 12), (mo % 12) + 1, 1) - timedelta(days=1)).day
            dt = _safe_date(int(yy), mo, last_day)
            if dt:
                candidates.append((dt, int(strike)))
    m = _RE_WEEKLY.match(s)
    if m:
        yy, monchar, dd, strike = m.groups()
        if 1 <= int(dd) <= 31 and int(strike) >= 500:
            dt = _safe_date(int(yy), MONTH1[monchar], int(dd))
            if dt:
                candidates.append((dt, int(strike)))

    expiry = strike = None
    if candidates:
        # prefer the candidate whose expiry is on/after entry_date - 1 (options can be
        # exited on their own expiry day) and closest to it; else the overall closest.
        plausible = [c for c in candidates if c[0] >= entry_date - timedelta(days=1)]
        pool = plausible or candidates
        expiry, strike = min(pool, key=lambda c: abs((c[0] - entry_date).days))

    return {
        "underlying": underlying,
        "opt_type": opt_type,
        "strike": strike,
        "expiry": expiry.isoformat() if expiry else None,
        "dte": (expiry - entry_date).days if expiry else None,
    }


def dte_bucket(dte) -> str:
    if dte is None:
        return "unknown"
    if dte <= 0:
        return "0"
    if dte == 1:
        return "1"
    if dte == 2:
        return "2"
    return "3+"


# ---------------------------------------------------------------------------
# structure + bias classification (per trade, from parsed legs)
# ---------------------------------------------------------------------------


def classify_structure(legs: list[dict]) -> str:
    n = len(legs)
    sides = [leg["side"] for leg in legs]
    types = [leg["opt_type"] for leg in legs]
    if n == 0:
        return "other"
    if all(s == "BUY" for s in sides):
        return "option_buy"
    if n == 1:
        return "other"  # naked single-leg short
    if n == 2:
        s0, s1 = sides
        t0, t1 = types
        k0, k1 = legs[0].get("strike"), legs[1].get("strike")
        if s0 == "SELL" and s1 == "SELL":
            if t0 == t1:
                return "other"  # two short legs, same type - ratio/back, not a defined structure
            if k0 is not None and k1 is not None and k0 == k1:
                return "straddle"
            return "strangle"
        if {s0, s1} == {"SELL", "BUY"} and t0 == t1:
            return "credit_spread"
        return "other"
    if n == 4:
        n_sell = sides.count("SELL")
        n_buy = sides.count("BUY")
        if n_sell == 2 and n_buy == 2:
            return "condor"
        return "other"
    return "other"


def bias_score(legs: list[dict]) -> int:
    """Per task definition: bearish = short calls dominant, bullish = short puts dominant.

    Driven by the SHORT legs only (a vertical spread's long wing is a hedge, not a directional
    signal - a bull put spread is short a put + long a further-OTM put; scoring both legs would
    net it to "neutral", which is wrong). Falls back to the BUY legs (long call = bullish, long
    put = bearish) only when there are no short legs at all, i.e. pure option-buying trades.
    """
    sell_ce = sum(
        1 for leg in legs if leg["side"] == "SELL" and leg["opt_type"] == "CE"
    )
    sell_pe = sum(
        1 for leg in legs if leg["side"] == "SELL" and leg["opt_type"] == "PE"
    )
    if sell_ce or sell_pe:
        return sell_pe - sell_ce
    buy_ce = sum(1 for leg in legs if leg["side"] == "BUY" and leg["opt_type"] == "CE")
    buy_pe = sum(1 for leg in legs if leg["side"] == "BUY" and leg["opt_type"] == "PE")
    return buy_ce - buy_pe


def bias_label(score: int) -> str:
    if score > 0:
        return "bullish"
    if score < 0:
        return "bearish"
    return "neutral"


# ---------------------------------------------------------------------------
# market data loaders + as-of (strictly-prior-day, no-lookahead) lookups
# ---------------------------------------------------------------------------


class DailySeries:
    """Sorted-by-date rows with a strict "last row before this date" lookup."""

    def __init__(self, rows: list[dict]):
        self.rows = sorted(rows, key=lambda r: r["date"])
        self.dates = [r["date"] for r in self.rows]

    def as_of_prior(self, d: str) -> dict | None:
        i = bisect.bisect_left(self.dates, d) - 1
        return self.rows[i] if i >= 0 else None

    def quantile(self, field: str, q: float) -> float | None:
        vals = sorted(r[field] for r in self.rows if r.get(field) is not None)
        if not vals:
            return None
        pos = (len(vals) - 1) * q
        lo = math.floor(pos)
        frac = pos - lo
        if lo + 1 < len(vals):
            return vals[lo] + frac * (vals[lo + 1] - vals[lo])
        return vals[lo]


def bucket_by_thresholds(v, lo, hi) -> str:
    if v is None or lo is None or hi is None:
        return "unknown"
    if v <= lo:
        return "low"
    if v >= hi:
        return "high"
    return "mid"


def sign_bucket(v, eps, pos="up", neg="down", flat="flat") -> str:
    if v is None:
        return "unknown"
    if v > eps:
        return pos
    if v < -eps:
        return neg
    return flat


class Intraday5m:
    """NIFTY 5-min bars, UTC epoch-second timestamps. Provides nearest-at-or-before lookup
    and per-IST-calendar-day opening price."""

    def __init__(self, path: Path):
        ts, close = [], []
        day_first_ts: dict[str, float] = {}
        day_open: dict[str, float] = {}
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                t = float(row["timestamp"])
                c = float(row["close"])
                o = float(row["open"])
                ts.append(t)
                close.append(c)
                d = datetime.fromtimestamp(t, tz=UTC).astimezone(IST).date().isoformat()
                if d not in day_first_ts or t < day_first_ts[d]:
                    day_first_ts[d] = t
                    day_open[d] = o
        order = sorted(range(len(ts)), key=lambda i: ts[i])
        self.ts = [ts[i] for i in order]
        self.close = [close[i] for i in order]
        self.day_open = day_open

    def at_or_before(self, epoch: float):
        i = bisect.bisect_right(self.ts, epoch) - 1
        if i < 0:
            return None
        return self.ts[i], self.close[i]

    def context(self, epoch: float, ist_date_str: str) -> dict:
        cur = self.at_or_before(epoch)
        prior60 = self.at_or_before(epoch - 3600)
        opn = self.day_open.get(ist_date_str)
        intraday_move = None
        momentum_60 = None
        if cur and opn:
            intraday_move = (cur[1] - opn) / opn
        if cur and prior60 and prior60[1]:
            momentum_60 = (cur[1] - prior60[1]) / prior60[1]
        return {"intraday_move": r2(intraday_move), "momentum_60min": r2(momentum_60)}


class RollingATM:
    """Rolling weekly ATM CALL/PUT IV, 5-min bars. Only one expiry is ever "current" in this
    file (it rolls to the next weekly contract on expiry), so a nearest-timestamp match is
    already a same-week match - no separate expiry filter needed."""

    MAX_GAP_S = (
        900  # 15min; wider gaps (holidays, feed drops) -> null rather than stale
    )

    def __init__(self, path: Path):
        self.by_type: dict[str, tuple[list[float], list[float]]] = {}
        buf: dict[str, list[tuple[float, float]]] = defaultdict(list)
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                if row["strike_offset"] != "ATM":
                    continue
                iv = row.get("iv")
                if not iv:
                    continue
                buf[row["option_type"]].append((float(row["timestamp"]), float(iv)))
        for opt_type, pairs in buf.items():
            pairs.sort()
            self.by_type[opt_type] = ([p[0] for p in pairs], [p[1] for p in pairs])

    def _nearest(self, ts_list, iv_list, epoch):
        if not ts_list:
            return None
        i = bisect.bisect_left(ts_list, epoch)
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(ts_list):
                gap = abs(ts_list[j] - epoch)
                if gap <= self.MAX_GAP_S and (best is None or gap < best[0]):
                    best = (gap, iv_list[j])
        return best[1] if best else None

    def atm_iv(self, epoch: float) -> float | None:
        vals = []
        for opt_type in ("CALL", "PUT"):
            ts_list, iv_list = self.by_type.get(opt_type, ([], []))
            v = self._nearest(ts_list, iv_list, epoch)
            if v is not None:
                vals.append(v)
        return r2(sum(vals) / len(vals)) if vals else None


# ---------------------------------------------------------------------------
# per-trade extraction
# ---------------------------------------------------------------------------


def to_ist(iso_z: str) -> datetime:
    return datetime.fromisoformat(iso_z.replace("Z", "+00:00")).astimezone(IST)


def build_trade(
    item: dict,
    algo_meta: dict,
    vix_series: DailySeries,
    iv_series: DailySeries,
    vix_terciles,
    intraday: Intraday5m,
    atm: RollingATM,
) -> dict | None:
    if item.get("backtestTrade") is True:
        return None
    if item.get("isActive"):
        return None
    created = item.get("createdAt")
    closed = item.get("closedOn")
    if not created or not closed:
        return None
    raw_legs = item.get("trades") or []
    if not raw_legs:
        return None

    entry_dt = to_ist(created)
    exit_dt = to_ist(closed)
    entry_date = entry_dt.date()
    entry_date_str = entry_date.isoformat()

    legs = []
    pts = 0.0
    rs = 0.0
    for leg in raw_legs:
        symbol = leg.get("symbol") or ""
        parsed = parse_symbol(symbol, entry_date)
        side = (leg.get("transactionType") or "").upper()
        entry_px = float(leg.get("entryPrice") or 0)
        exit_px = float(
            leg.get("exitPrice") if leg.get("exitPrice") is not None else entry_px
        )
        qty = float(leg.get("quantity") or 1)
        lot = leg.get("multiplier") or LOT_FALLBACK.get(parsed["underlying"], 75)
        sign = 1 if side == "BUY" else -1
        pts += sign * (exit_px - entry_px) * qty
        rs += sign * (exit_px - entry_px) * qty * lot
        legs.append(
            {
                "symbol": symbol,
                "side": side if side in ("BUY", "SELL") else "SELL",
                "opt_type": parsed["opt_type"],
                "strike": parsed["strike"],
                "expiry": parsed["expiry"],
                "underlying": parsed["underlying"],
                "entry_px": entry_px,
                "exit_px": exit_px,
                "multiplier": lot,
            }
        )

    underlying = (
        legs[0]["underlying"] if legs else algo_meta.get("underlying") or "NIFTY"
    )
    dtes = [
        l["expiry"] and (date.fromisoformat(l["expiry"]) - entry_date).days
        for l in legs
    ]
    dtes = [d for d in dtes if d is not None]
    dte = min(dtes) if dtes else None

    max_lots = item.get("maxLots") or 1
    margin_total = item.get("marginRequired")
    margin_per_lot = margin_total / max_lots if margin_total and max_lots else None

    structure = classify_structure(legs)
    b_score = bias_score(legs)
    bias = bias_label(b_score)

    prior_vix = vix_series.as_of_prior(entry_date_str)
    prior_iv = iv_series.as_of_prior(entry_date_str)

    vix_level = prior_vix["vix"] if prior_vix else None
    vix_lo, vix_hi = vix_terciles
    trend_20d = prior_vix["trend_20d"] if prior_vix else None
    vix_chg_5d = prior_vix.get("vix_chg_5d") if prior_vix else None
    iv_rank = prior_iv.get("iv_rank") if prior_iv else None
    skew = prior_iv.get("skew") if prior_iv else None

    ctx = intraday.context(entry_dt.timestamp(), entry_date_str)
    atm_iv_entry = atm.atm_iv(entry_dt.timestamp())

    momentum_sign = sign_bucket(
        ctx["momentum_60min"], MOMENTUM_FLAT_EPS, "up", "down", "flat"
    )
    momentum_aligned = None
    if bias in ("bullish", "bearish") and momentum_sign in ("up", "down"):
        momentum_aligned = (bias == "bullish" and momentum_sign == "up") or (
            bias == "bearish" and momentum_sign == "down"
        )

    return {
        "algo_id": algo_meta["id"],
        "algo_name": algo_meta["name"],
        "category": algo_meta["category"],
        "underlying": underlying,
        "structure": structure,
        "bias": bias,
        "bias_score": b_score,
        "entry_ts_ist": entry_dt.isoformat(),
        "entry_date": entry_date_str,
        "exit_ts_ist": exit_dt.isoformat(),
        "pnl_pts": r2(pts),
        "pnl_rs": r2(rs),
        "margin_per_lot": r2(margin_per_lot),
        "return_pct_margin": r2(100 * rs / margin_per_lot) if margin_per_lot else None,
        "n_legs": len(legs),
        "dte": dte,
        "dte_bucket": dte_bucket(dte),
        "trend_20d": trend_20d or "unknown",
        "vix": r2(vix_level),
        "vix_tercile": bucket_by_thresholds(vix_level, vix_lo, vix_hi),
        "vix_chg_5d_sign": sign_bucket(vix_chg_5d, VIX_CHG_FLAT_EPS),
        "iv_rank": r2(iv_rank),
        "iv_rank_tercile": bucket_by_thresholds(iv_rank, 33.33, 66.67),
        "skew": r2(skew),
        "skew_sign": sign_bucket(skew, SKEW_FLAT_EPS, "positive", "negative", "flat"),
        "intraday_move": ctx["intraday_move"],
        "momentum_60min": ctx["momentum_60min"],
        "momentum_sign": momentum_sign,
        "momentum_aligned": momentum_aligned,
        "atm_iv_entry": atm_iv_entry,
        "legs": legs,
    }


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------

CELL_DIMS = [
    ("trend_20d", ["bull", "side", "bear", "unknown"]),
    ("vix_tercile", ["low", "mid", "high", "unknown"]),
    ("vix_chg_5d_sign", ["up", "down", "flat", "unknown"]),
    ("iv_rank_tercile", ["low", "mid", "high", "unknown"]),
    ("skew_sign", ["positive", "negative", "flat", "unknown"]),
    ("dte_bucket", ["0", "1", "2", "3+", "unknown"]),
]


def group_stats(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {
            "n": 0,
            "wr": None,
            "pf": None,
            "pf_inf": False,
            "avg_rs": None,
            "thin": True,
        }
    wins = sum(1 for t in trades if t["pnl_rs"] and t["pnl_rs"] > 0)
    win_sum = sum(t["pnl_rs"] for t in trades if t["pnl_rs"] and t["pnl_rs"] > 0)
    loss_sum = sum(t["pnl_rs"] for t in trades if t["pnl_rs"] and t["pnl_rs"] < 0)
    pf_inf = loss_sum == 0 and win_sum > 0
    pf = None if pf_inf or loss_sum == 0 else abs(win_sum / loss_sum)
    avg_rs = sum(t["pnl_rs"] or 0 for t in trades) / n
    return {
        "n": n,
        "wr": r2(100 * wins / n),
        "pf": r2(pf),
        "pf_inf": pf_inf,
        "avg_rs": r2(avg_rs),
        "thin": n < MIN_CELL_N,
    }


def cells_for(trades: list[dict]) -> dict:
    out = {}
    for dim, _buckets in CELL_DIMS:
        by_bucket = defaultdict(list)
        for t in trades:
            by_bucket[t[dim]].append(t)
        out[dim] = {b: group_stats(ts) for b, ts in by_bucket.items()}
    return out


def max_drawdown_rs(trades_sorted_by_exit: list[dict]) -> float:
    peak = -math.inf
    cum = 0.0
    dd = 0.0
    for t in trades_sorted_by_exit:
        cum += t["pnl_rs"] or 0
        if cum > peak:
            peak = cum
        dd = min(dd, cum - peak)
    return dd


def per_algo_record(algo_meta: dict, trades: list[dict]) -> dict:
    trades_sorted = sorted(trades, key=lambda t: t["exit_ts_ist"])
    base = group_stats(trades)
    max_dd = r2(max_drawdown_rs(trades_sorted))
    total_rs = sum(t["pnl_rs"] or 0 for t in trades)
    calmar = r2(total_rs / abs(max_dd)) if max_dd and max_dd != 0 else None
    avg_pts = (
        r2(sum(t["pnl_pts"] or 0 for t in trades) / len(trades)) if trades else None
    )
    margins = [t["margin_per_lot"] for t in trades if t["margin_per_lot"]]
    margin_per_lot = r2(sum(margins) / len(margins)) if margins else None

    structure_counts = Counter(t["structure"] for t in trades)
    bias_counts = Counter(t["bias"] for t in trades)

    return {
        "id": algo_meta["id"],
        "name": algo_meta["name"],
        "category": algo_meta["category"],
        "structure": structure_counts.most_common(1)[0][0]
        if structure_counts
        else "other",
        "bias": bias_counts.most_common(1)[0][0] if bias_counts else "neutral",
        "trades": base["n"],
        "wr": base["wr"],
        "pf": base["pf"],
        "pf_inf": base["pf_inf"],
        "avg_pts": avg_pts,
        "avg_rs": base["avg_rs"],
        "max_dd_rs": max_dd,
        "calmar": calmar,
        "margin_per_lot": margin_per_lot,
        "cells": cells_for(trades),
    }


# ---------------------------------------------------------------------------
# findings
# ---------------------------------------------------------------------------


def finding_short_call_vs_put(trades: list[dict]) -> dict:
    short_legged = {"credit_spread", "strangle", "straddle", "condor"}
    calls = [
        t for t in trades if t["structure"] in short_legged and t["bias"] == "bearish"
    ]
    puts = [
        t for t in trades if t["structure"] in short_legged and t["bias"] == "bullish"
    ]

    def avg_pct(ts):
        vals = [
            t["return_pct_margin"] for t in ts if t["return_pct_margin"] is not None
        ]
        return r2(sum(vals) / len(vals)) if vals else None

    call_avg = avg_pct(calls)
    put_avg = avg_pct(puts)
    holds = None
    if call_avg is not None and put_avg is not None:
        holds = call_avg > put_avg
    return {
        "hypothesis": "short-call-dominant (bearish) spreads outperform short-put-dominant "
        "(bullish) spreads on avg return-on-margin %",
        "short_call_avg_pct_margin": call_avg,
        "short_call_n": len(calls),
        "short_put_avg_pct_margin": put_avg,
        "short_put_n": len(puts),
        "holds": holds,
    }


def finding_credit_spread_loss_by_dte(trades: list[dict]) -> dict:
    cs = [t for t in trades if t["structure"] == "credit_spread"]
    by_bucket = defaultdict(list)
    for t in cs:
        by_bucket[t["dte_bucket"]].append(t)
    rates = {}
    for b, ts in by_bucket.items():
        n = len(ts)
        losses = sum(1 for t in ts if t["pnl_rs"] is not None and t["pnl_rs"] < 0)
        rates[b] = {"n": n, "loss_rate_pct": r2(100 * losses / n) if n else None}
    order = ["0", "1", "2", "3+"]
    seq = [
        rates[b]["loss_rate_pct"]
        for b in order
        if b in rates and rates[b]["loss_rate_pct"] is not None
    ]
    holds = None
    if len(seq) >= 2:
        holds = seq[0] >= seq[-1]  # 0DTE loss rate >= 3+DTE loss rate
    return {
        "hypothesis": "credit-spread loss rate is higher at 0DTE than at 3+DTE (gamma risk "
        "into same-day expiry)",
        "by_dte_bucket": rates,
        "holds": holds,
    }


def finding_momentum_follow(algo_records: list[dict], trades_by_algo: dict) -> dict:
    ranked = sorted(
        (a for a in algo_records if a["trades"] >= MIN_CELL_N),
        key=lambda a: a["avg_rs"] or -1e18,
        reverse=True,
    )
    top_n = max(1, round(len(ranked) * 0.10))
    top_ids = {a["id"] for a in ranked[:top_n]}

    def aligned_share(ids):
        pool = [
            t
            for aid in ids
            for t in trades_by_algo[aid]
            if t["momentum_aligned"] is not None
        ]
        if not pool:
            return None, 0
        aligned = sum(1 for t in pool if t["momentum_aligned"])
        return r2(100 * aligned / len(pool)), len(pool)

    top_share, top_n_trades = aligned_share(top_ids)
    all_ids = {a["id"] for a in algo_records}
    all_share, all_n_trades = aligned_share(all_ids)
    holds = None
    if top_share is not None and all_share is not None:
        holds = (
            top_share - all_share
        ) > 5  # top decile at least 5pp more momentum-aligned
    return {
        "hypothesis": "top-decile algos (by avg Rs/trade) are disproportionately "
        "momentum-following (entries whose directional bias matches the trailing 60min move)",
        "top_decile_n_algos": len(top_ids),
        "top_decile_momentum_aligned_pct": top_share,
        "top_decile_n_trades": top_n_trades,
        "all_algos_momentum_aligned_pct": all_share,
        "all_algos_n_trades": all_n_trades,
        "holds": holds,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    print("loading reference data...", flush=True)
    algo_list = {a["_id"]: a for a in load(ALGO_LIST_PATH)}
    explore = load(EXPLORE_PATH)["algos"]

    vix_rows = load(NIFTY_VIX_PATH)
    vix_series = DailySeries(vix_rows)
    vix_lo = vix_series.quantile("vix", 1 / 3)
    vix_hi = vix_series.quantile("vix", 2 / 3)
    print(f"  vix terciles (1Y): lo={vix_lo:.2f} hi={vix_hi:.2f}", flush=True)

    iv_rows = load(IV_DAILY_PATH)
    iv_series = DailySeries(iv_rows)

    print("indexing intraday NIFTY 5m + rolling ATM IV...", flush=True)
    intraday = Intraday5m(NIFTY_5M_PATH)
    atm = RollingATM(ROLLING_OPT_PATH)

    all_trades: list[dict] = []
    trades_by_algo: dict[str, list[dict]] = {}
    algo_records = []
    n_items_seen = 0
    n_backtest_skipped = 0
    n_no_legs = 0
    n_incomplete = 0

    for e in explore:
        aid = e["id"]
        meta_raw = algo_list.get(aid, {})
        meta = {
            "id": aid,
            "name": e.get("name") or meta_raw.get("name") or aid,
            "category": e.get("display_category")
            or meta_raw.get("displayCategory")
            or "",
            "underlying": e.get("underlying") or meta_raw.get("underlying") or "NIFTY",
        }
        adir = ADVICES_DIR / aid
        trades: list[dict] = []
        if adir.is_dir():
            for f in adir.glob("*.json"):
                try:
                    items = json.loads(f.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                for item in items:
                    n_items_seen += 1
                    if item.get("backtestTrade") is True:
                        n_backtest_skipped += 1
                        continue
                    if not (item.get("trades") or []):
                        n_no_legs += 1
                        continue
                    t = build_trade(
                        item,
                        meta,
                        vix_series,
                        iv_series,
                        (vix_lo, vix_hi),
                        intraday,
                        atm,
                    )
                    if t is None:
                        n_incomplete += 1
                        continue
                    trades.append(t)
        trades_by_algo[aid] = trades
        all_trades.extend(trades)
        algo_records.append(per_algo_record(meta, trades))

    print(
        f"items_seen={n_items_seen} backtest_skipped={n_backtest_skipped} "
        f"no_legs={n_no_legs} incomplete={n_incomplete} trades_built={len(all_trades)}",
        flush=True,
    )

    # global: same cells, pooled across ALL algos, grouped by structure+bias
    by_structure_bias = defaultdict(list)
    for t in all_trades:
        by_structure_bias[f"{t['structure']}|{t['bias']}"].append(t)
    global_block = {
        "by_structure_bias": {
            key: {**group_stats(ts), "cells": cells_for(ts)}
            for key, ts in sorted(by_structure_bias.items())
        }
    }

    findings = {
        "short_call_vs_short_put_avg_pct": finding_short_call_vs_put(all_trades),
        "credit_spread_loss_rate_by_dte": finding_credit_spread_loss_by_dte(all_trades),
        "momentum_follow_top_decile": finding_momentum_follow(
            algo_records, trades_by_algo
        ),
    }

    panel = {
        "generated_at": datetime.now(tz=IST).isoformat(),
        "note": "Every closed, non-backtest advice across the 118 explore_data.json algos, "
        "joined to market context AS OF ENTRY (daily fields use the strictly-prior trading "
        "day's close - no lookahead). See regime_study.py for methodology and assumptions.",
        "coverage": {
            "algos": len(algo_records),
            "trades": len(all_trades),
            "items_seen": n_items_seen,
            "backtest_skipped": n_backtest_skipped,
            "no_legs_skipped": n_no_legs,
            "incomplete_skipped": n_incomplete,
            "vix_tercile_1y": {"lo": r2(vix_lo), "hi": r2(vix_hi)},
        },
        "algos": algo_records,
        "global": global_block,
        "findings": findings,
    }

    OUT_PANEL.write_text(json.dumps(panel))
    print(f"wrote {OUT_PANEL} ({OUT_PANEL.stat().st_size / 1024:.0f} KB)", flush=True)

    write_trades_table(all_trades)

    print("\n--- findings ---", flush=True)
    for k, v in findings.items():
        print(f"{k}: holds={v.get('holds')}", flush=True)


def write_trades_table(trades: list[dict]) -> None:
    import pandas as pd

    rows = []
    for t in trades:
        row = {k: v for k, v in t.items() if k != "legs"}
        row["legs_json"] = json.dumps(t["legs"])
        rows.append(row)
    df = pd.DataFrame(rows)
    try:
        df.to_parquet(OUT_TRADES_PARQUET, index=False)
        print(f"wrote {OUT_TRADES_PARQUET} rows={len(df)}", flush=True)
    except ImportError:
        df.to_csv(OUT_TRADES_CSV, index=False)
        print(f"wrote {OUT_TRADES_CSV} (no pyarrow) rows={len(df)}", flush=True)


if __name__ == "__main__":
    main()
