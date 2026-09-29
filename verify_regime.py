#!/usr/bin/env python3
"""Independent adversarial re-check of regime_panel.json for 5 picked algos.

Written fresh from raw data/advices/*.json + data/algo_list.json + nifty_vix_daily.json,
deliberately NOT importing regime_study.py, so a bug shared by both scripts would still
show up as a real mismatch against hand-checkable raw numbers.
"""

import json
import os
import bisect
from datetime import datetime, date
from zoneinfo import ZoneInfo

ROOT = "/Users/ck/stratzy-credit-spread-report"
IST = ZoneInfo("Asia/Kolkata")

PICKS = [
    ("698075eaf867bf12b20442e5", "top1"),
    ("6a8beff84133d17c657f0452", "top2"),
    ("6a81bb9c47197c055b5b57c8", "random1"),
    ("676aa59fc8f0da44991f2e90", "random2"),
    ("6845cc951f9886e2caa9c466", "option_buying"),
]

vix_rows = sorted(
    json.load(open(f"{ROOT}/nifty_vix_daily.json")), key=lambda r: r["date"]
)
vix_dates = [r["date"] for r in vix_rows]
vix_vals_all = sorted(r["vix"] for r in vix_rows if r.get("vix") is not None)


def vix_quantile(q):
    vals = vix_vals_all
    pos = (len(vals) - 1) * q
    lo = int(pos)
    frac = pos - lo
    if lo + 1 < len(vals):
        return vals[lo] + frac * (vals[lo + 1] - vals[lo])
    return vals[lo]


VIX_LO = vix_quantile(1 / 3)
VIX_HI = vix_quantile(2 / 3)
print(f"independent vix terciles: lo={VIX_LO:.4f} hi={VIX_HI:.4f}")


def vix_as_of_prior(entry_date_str):
    i = bisect.bisect_left(vix_dates, entry_date_str) - 1
    if i < 0:
        return None
    return vix_rows[i]


def tercile(v):
    if v is None:
        return "unknown"
    if v <= VIX_LO:
        return "low"
    if v >= VIX_HI:
        return "high"
    return "mid"


def to_ist(iso_z):
    return datetime.fromisoformat(iso_z.replace("Z", "+00:00")).astimezone(IST)


panel = json.load(open(f"{ROOT}/regime_panel.json"))
panel_by_id = {a["id"]: a for a in panel["algos"]}

for aid, label in PICKS:
    adir = f"{ROOT}/data/advices/{aid}"
    n_trades = 0
    n_wins = 0
    total_rs = 0.0
    cell_counts = {
        "low": [0, 0],
        "mid": [0, 0],
        "high": [0, 0],
        "unknown": [0, 0],
    }  # [n, wins] just for wr later
    cell_rs = {"low": [], "mid": [], "high": [], "unknown": []}
    lookahead_violations = 0
    sample_join = []
    for fn in sorted(os.listdir(adir)):
        items = json.load(open(os.path.join(adir, fn)))
        for it in items:
            if it.get("backtestTrade") is True:
                continue
            if it.get("isActive"):
                continue
            created = it.get("createdAt")
            closed = it.get("closedOn")
            if not created or not closed:
                continue
            legs = it.get("trades") or []
            if not legs:
                continue
            entry_dt = to_ist(created)
            entry_date_str = entry_dt.date().isoformat()
            rs = 0.0
            for leg in legs:
                entry_px = float(leg.get("entryPrice") or 0)
                exit_px = float(
                    leg.get("exitPrice")
                    if leg.get("exitPrice") is not None
                    else entry_px
                )
                qty = float(leg.get("quantity") or 1)
                lot = leg.get("multiplier") or 75
                side = (leg.get("transactionType") or "").upper()
                sign = 1 if side == "BUY" else -1
                rs += sign * (exit_px - entry_px) * qty * lot
            n_trades += 1
            if rs > 0:
                n_wins += 1
            total_rs += rs
            prior = vix_as_of_prior(entry_date_str)
            vix_level = prior["vix"] if prior else None
            prior_date = prior["date"] if prior else None
            b = tercile(vix_level)
            cell_rs[b].append(rs)
            # lookahead check: prior row's date must be strictly < entry_date
            if prior_date is not None and prior_date >= entry_date_str:
                lookahead_violations += 1
            if len(sample_join) < 3:
                sample_join.append((entry_date_str, prior_date, vix_level, b))

    wr = 100 * n_wins / n_trades if n_trades else None
    print(f"\n=== {label}: {aid} ===")
    print(
        f"  hand-recomputed: trades={n_trades} wins={n_wins} wr={wr:.4f} total_rs={total_rs:.2f}"
    )
    p = panel_by_id.get(aid)
    if p:
        panel_total_rs = (p["avg_rs"] or 0) * p["trades"]
        print(
            f"  panel:           trades={p['trades']} wr={p['wr']} avg_rs={p['avg_rs']} -> implied total_rs={panel_total_rs:.2f}"
        )
        print(
            f"  MATCH trades: {n_trades == p['trades']}  MATCH wr(~1e-2): {abs(wr - p['wr']) < 0.05 if p['wr'] is not None else 'n/a'}  MATCH total_rs(~1): {abs(total_rs - panel_total_rs) < 5}"
        )
    else:
        print("  NOT FOUND IN PANEL")
    print(
        f"  lookahead_violations (prior vix date >= entry date): {lookahead_violations}"
    )
    print(f"  sample entry_date -> prior_vix_date, vix, tercile: {sample_join}")
    for bucket in ("low", "mid", "high"):
        vals = cell_rs[bucket]
        n = len(vals)
        wins_b = sum(1 for v in vals if v > 0)
        avg = sum(vals) / n if n else None
        wr_b = 100 * wins_b / n if n else None
        print(f"    vix_tercile={bucket}: n={n} wr={wr_b} avg_rs={avg}")
        if p:
            pc = p["cells"]["vix_tercile"].get(bucket)
            print(f"      panel cell: {pc}")
