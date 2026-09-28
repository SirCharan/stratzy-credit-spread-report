#!/usr/bin/env python3
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

SRC = Path(__file__).parent / "option_buying_analysis.json"
OUT = Path(__file__).parent

FAMILIES = [
    {
        "id": "signal",
        "title": "Proprietary entry signals — different brains, same product",
        "subtitle": "Each uses a unique signal to pick CE vs PE and strike. All buy single options intraday. Exit rules vary.",
        "members": [
            "Stratzy's Option Tracker",
            "Index Scalper",
            "TejNiti",
            "SkewHunter",
            "SkewHunter TSL",
            "Index Sniper",
        ],
    },
    {
        "id": "grid",
        "title": "GRID exit — scale in/out at price levels",
        "subtitle": "Enters long option, manages exit via grid levels (not single SL). Can pyramid or average.",
        "members": [
            "Burst GRID (30% SL)",
            "Vacuum GRID (35% SL)",
            "Watchful 33% SL Grid",
        ],
    },
    {
        "id": "tsl",
        "title": "Trailing stop loss (TSL) — ride winners, trail stop",
        "subtitle": "Name shows TSL % (25–40%). Stop trails as premium rises. Lower WR but captures momentum bursts.",
        "members": [
            "Settle-Down 40% TSL",
            "Wise-Move 25% TSL",
            "Nischay 40% TSL",
            "Only-Calls 40% TSL",
            "Safe-Khel 40% TSL",
            "Ghar-Aangan 30% TSL",
            "Aaram-Se 30% TSL",
            "Aastha 35% TSL",
            "Dhyaan 35% TSL",
            "Thrifty 40% TSL",
            "Free-Lunch 30% TSL",
        ],
    },
    {
        "id": "fixed_sl",
        "title": "Fixed stop loss — hard % cap on loss",
        "subtitle": "SL in name (25–40%). If premium drops X%, exit. Simpler risk, no trailing.",
        "members": [
            "Savdhaan 35% SL",
            "Sookshma-Nazar 25% SL",
            "Shanti 40% SL",
            "Sahas 40% SL",
            "First-Step 25% SL",
        ],
    },
    {
        "id": "fixed_rr",
        "title": "Fixed risk-reward (RR 1:2 or 1:3)",
        "subtitle": "Targets fixed multiple of risk. Exits at target OR stop. Lower frequency, defined payoff.",
        "members": [
            "Fixed RR 1:3 (30% SL)",
            "Prudent 30%SL FixedRR 1:3",
            "Fortuna 30%SL FixedRR 1:3",
            "Equilibrium 25%SL FixedRR 1:3",
            "Aequitas 25%SL FixedRR 1:3",
            "Patience 35%SL FixedRR 1:3",
            "Vigil 25%SL FixedRR 1:3",
            "Seed-Fund 40% SL FixedRR 1:3",
            "Chhota-Move 30% SL FixedRR 1:2",
        ],
    },
    {
        "id": "partial",
        "title": "Partial target — book profits in chunks",
        "subtitle": "Exits portion at first target, trails rest. Highest win rates in category (70%+).",
        "members": [
            "Harbor 33%SL with Partial Target",
            "Sunrise 33%SL + Partial Target",
            "Cornerstone 33%SL + Partial Target",
        ],
    },
]

DIFFS = {
    "Stratzy's Option Tracker": "Multi-index tracker (NIFTY/FINNIFTY). Highest all-time pts (+4224). 61% WR. Stratzy flagship buying algo.",
    "Index Scalper": "Fast scalping on index moves. High trade count, 46% WR but huge winners (+2457 pts all-time).",
    "TejNiti": "Momentum burst signal. 65% WR — highest among signal algos. Smaller pts/trade.",
    "SkewHunter": "IV skew hunting for entry. 39% WR, big winners when skew pays off.",
    "SkewHunter TSL": "Same skew entry + trailing stop exit. More 2026 activity than base SkewHunter.",
    "Burst GRID (30% SL)": "#1 in 2026 YTD (+1658 pts). Grid exit on momentum bursts. 52% WR.",
    "Vacuum GRID (35% SL)": "Grid on volatility vacuum setups. #2 in 2026 (+1132 pts).",
    "Savdhaan 35% SL": 'Conservative fixed 35% SL. +1017 pts in 2026 alone. Hindi "caution" — defensive sizing.',
    "Settle-Down 40% TSL": "TSL after volatility settles. Strong 2026 (+802 pts).",
    "Only-Calls 40% TSL": "CALLS ONLY with 40% TSL. Never buys puts.",
    "Harbor 33%SL with Partial Target": "73% WR — best win rate in top 25. Books partial profits early.",
    "Fixed RR 1:3 (30% SL)": "Strict 1:3 RR. 37% WR but defined payoff shape.",
    "Equilibrium 25%SL FixedRR 1:3": "67% WR, lower pts — quality over quantity.",
}

PAIRWISE_HEADLINES = {
    (
        "Burst GRID (30% SL)",
        "Vacuum GRID (35% SL)",
    ): "same GRID exit, different entry brain — momentum burst vs vol vacuum",
    (
        "Vacuum GRID (35% SL)",
        "Watchful 33% SL Grid",
    ): "high-volume GRID leaders vs low-frequency Watchful grid",
    (
        "Settle-Down 40% TSL",
        "Wise-Move 25% TSL",
    ): "both TSL — Settle waits for vol to calm, Wise-Move uses tighter 25% trail",
    (
        "SkewHunter",
        "SkewHunter TSL",
    ): "identical skew entry signal — only the exit changes (discretionary vs 40% TSL)",
    (
        "Savdhaan 35% SL",
        "Sookshma-Nazar 25% SL",
    ): "both fixed SL — Savdhaan wider stop, Sookshma tighter 25% cap",
    (
        "Harbor 33%SL with Partial Target",
        "Sunrise 33%SL + Partial Target",
    ): "same partial-book exit style — different entry signals / PE tilt",
}

PAIRWISE_HINTS = {
    ("Burst GRID (30% SL)", "Vacuum GRID (35% SL)"): [
        "Burst enters on momentum expansion; Vacuum enters when vol collapses into a “vacuum” (mean-revert snap).",
        "Burst runs ~3× more trades — higher turnover, more grid levels hit per month.",
    ],
    ("Vacuum GRID (35% SL)", "Watchful 33% SL Grid"): [
        "Watchful is a lighter, selective grid — only 21 live trades vs 287 on Vacuum.",
        "Watchful skews more PE (67%) vs Vacuum’s near-even CE/PE — different directional filter on same exit mechanic.",
    ],
    ("Settle-Down 40% TSL", "Wise-Move 25% TSL"): [
        "Settle-Down name = enters after volatility settles; Wise-Move trails tighter (25% vs 40%).",
        "Tighter TSL cuts winners earlier but caps give-back — expect lower avg win, possibly higher WR.",
    ],
    ("SkewHunter", "SkewHunter TSL"): [
        "Same skew-hunt entry — base SkewHunter exits differently; TSL variant adds systematic trailing stop.",
        "TSL version traded more in 2026 with positive YTD while base SkewHunter is negative all-time.",
    ],
    ("Savdhaan 35% SL", "Sookshma-Nazar 25% SL"): [
        "Savdhaan = “caution” — wider 35% hard stop, strong 2026 run. Sookshma = tighter 25% SL, smaller losses but fewer home runs.",
    ],
    ("Fixed RR 1:3 (30% SL)", "Prudent 30%SL FixedRR 1:3"): [
        "Both target 1:3 RR with ~30% stop — Prudent is a separate signal/branding with more PE-heavy mix.",
    ],
    ("Harbor 33%SL with Partial Target", "Sunrise 33%SL + Partial Target"): [
        "Both book partial profits then trail — Harbor has best WR in top 25 (73%). Sunrise is more PE-tilted.",
    ],
}


def short(name):
    return name.replace("Stratzy's ", "")


def fmt_trade(r):
    legs = r["legs"]
    buy = next((l for l in legs if l["transactionType"] == "BUY"), legs[0])
    return {
        "date": r["closed"],
        "pts": r["points_net"],
        "inr": r["calc_pnl_1lot"],
        "side": r["side"],
        "sym": buy["symbol"],
        "entry": buy["entryPrice"],
        "exit": buy["exitPrice"],
        "entry_premium": r.get("entry_premium"),
    }


def parse_features(name):
    n = name.lower()
    feats = {"exit": "signal", "side": "both"}
    m = re.search(r"(\d+)%", name)
    if m:
        feats["sl"] = int(m.group(1))
    if "tsl" in n:
        feats["exit"] = "trailing_sl"
    elif "grid" in n:
        feats["exit"] = "grid"
    elif "partial" in n or "target" in n:
        feats["exit"] = "partial_target"
    elif "fixedrr" in n.replace(" ", "") or "rr 1:" in n:
        feats["exit"] = "fixed_rr"
        rr = re.search(r"1:(\d)", name)
        if rr:
            feats["rr"] = f"1:{rr.group(1)}"
    elif " sl" in n or "%sl" in n.replace(" ", ""):
        feats["exit"] = "fixed_sl"
    if "only-calls" in n or "only calls" in n:
        feats["side"] = "ce_only"
    elif "only-put" in n or "only put" in n:
        feats["side"] = "pe_only"
    return feats


def _exit_label(f):
    labels = {
        "grid": "GRID levels",
        "trailing_sl": "trailing stop",
        "fixed_sl": "fixed % stop",
        "fixed_rr": f"fixed RR {f.get('rr', '1:3')}",
        "partial_target": "partial profit + trail",
        "signal": "signal-based exit",
    }
    return labels.get(f.get("exit"), f.get("exit", "unknown"))


def build_pairwise(prev, nxt, family):
    pf, nf = parse_features(prev["name"]), parse_features(nxt["name"])
    key = (prev["name"], nxt["name"])
    bullets = list(PAIRWISE_HINTS.get(key, []))

    if family["id"] == "signal" and prev["name"] != nxt["name"]:
        if "SkewHunter" in prev["name"] and "SkewHunter" in nxt["name"]:
            pass  # covered by hints
        else:
            bullets.append(
                f"Entry model: {prev['short']} and {nxt['short']} use different proprietary signals "
                f"to pick CE vs PE — not just a parameter tweak."
            )

    if pf.get("exit") != nf.get("exit"):
        bullets.append(
            f"Exit mechanics: {prev['short']} uses {_exit_label(pf)}; "
            f"{nxt['short']} uses {_exit_label(nf)}."
        )
    elif pf.get("sl") and nf.get("sl") and pf["sl"] != nf["sl"]:
        bullets.append(
            f"Stop width: {pf['sl']}% on {prev['short']} vs {nf['sl']}% on {nxt['short']} — "
            f"{'tighter stop on ' + nxt['short'] if nf['sl'] < pf['sl'] else 'wider stop on ' + nxt['short']}."
        )

    if pf.get("side") != nf.get("side"):
        side_txt = {
            "ce_only": "calls only",
            "pe_only": "puts only",
            "both": "both sides",
        }
        bullets.append(
            f"Side filter: {prev['short']} = {side_txt.get(pf['side'], pf['side'])}; "
            f"{nxt['short']} = {side_txt.get(nf['side'], nf['side'])}."
        )
    elif abs(prev["ce_pct"] - nxt["ce_pct"]) >= 12:
        bullets.append(
            f"Directional mix: {prev['short']} {prev['ce_pct']}% CE / {prev['pe_pct']}% PE vs "
            f"{nxt['short']} {nxt['ce_pct']}% CE / {nxt['pe_pct']}% PE."
        )

    ytd_d = round(nxt["ytd_pts"] - prev["ytd_pts"], 1)
    bullets.append(
        f"2026 net: {nxt['short']} {nxt['ytd_pts']:+.1f} pts vs {prev['short']} {prev['ytd_pts']:+.1f} pts "
        f"({ytd_d:+.1f} pts gap)."
    )

    wr_d = round(nxt["win_rate"] - prev["win_rate"], 1)
    wr_note = "higher hit rate" if wr_d > 0 else "lower hit rate"
    if wr_d <= 0 and nxt["avg_win"] > prev["avg_win"]:
        wr_note = "lower WR but bigger avg winners"
    bullets.append(
        f"Trade WR: {nxt['win_rate']}% vs {prev['win_rate']}% ({wr_d:+.1f} pp) — {wr_note}."
    )

    bullets.append(
        f"Avg win/loss (pts): {nxt['short']} +{nxt['avg_win']}/{nxt['avg_loss']} vs "
        f"+{prev['avg_win']}/{prev['avg_loss']}."
    )

    tpm_d = round(nxt["trades_pm"] - prev["trades_pm"], 1)
    if abs(tpm_d) >= 1.5:
        bullets.append(
            f"Activity: {nxt['trades_pm']}/mo vs {prev['trades_pm']}/mo on {prev['short']} "
            f"({'more' if tpm_d > 0 else 'fewer'} signals)."
        )

    if (
        prev.get("min_capital")
        and nxt.get("min_capital")
        and prev["min_capital"] != nxt["min_capital"]
    ):
        bullets.append(
            f"Min capital (Stratzy): ₹{nxt['min_capital']:,} vs ₹{prev['min_capital']:,}."
        )

    headline = PAIRWISE_HEADLINES.get(key)
    if not headline:
        if pf.get("exit") == nf.get("exit") and family["id"] != "signal":
            headline = (
                f"same {nf.get('exit', 'exit')} family — parameter & signal differences"
            )
        else:
            headline = (
                f"{_exit_label(pf)} vs {_exit_label(nf)} — what changes step to step"
            )

    return {
        "from": prev["name"],
        "to": nxt["name"],
        "from_short": prev["short"],
        "to_short": nxt["short"],
        "headline": headline,
        "bullets": bullets[:6],
    }


def business_days(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d.isoformat()
        d += timedelta(days=1)


def main():
    with open(SRC) as f:
        analyses = json.load(f)
    by_name = {a["name"]: a for a in analyses}
    # analyses = ranked + thin (analyze_option_buying.py); calendars/examples are only
    # meaningful for ranked (>= MIN_TRADES closed trades) algos, so no arbitrary 25-cap.
    top25 = [a for a in analyses if not a.get("thin")]

    start, end = date(2026, 1, 1), date(2026, 6, 15)
    all_days = list(business_days(start, end))

    calendars = {}
    for a in top25:
        day_pts = defaultdict(float)
        day_n = defaultdict(int)
        for r in a["rows"]:
            if r.get("backtestTrade") or not r["closed"].startswith("2026"):
                continue
            day_pts[r["closed"]] += r["points_net"]
            day_n[r["closed"]] += 1
        cells = []
        for d in all_days:
            if d in day_pts:
                p = round(day_pts[d], 1)
                cells.append(
                    {
                        "date": d,
                        "pts": p,
                        "trades": day_n[d],
                        "status": "win" if p > 0 else "loss" if p < 0 else "flat",
                    }
                )
            else:
                cells.append({"date": d, "pts": 0, "trades": 0, "status": "none"})
        calendars[a["name"]] = {
            "short": short(a["name"]),
            "cells": cells,
            "win_days": sum(1 for c in cells if c["status"] == "win"),
            "loss_days": sum(1 for c in cells if c["status"] == "loss"),
            "idle_days": sum(1 for c in cells if c["status"] == "none"),
        }

    examples = {}
    for a in top25:
        rows = [r for r in a["rows"] if not r.get("backtestTrade")]
        wins = sorted(
            [r for r in rows if r["points_net"] > 0], key=lambda x: -x["points_net"]
        )
        losses = sorted(
            [r for r in rows if r["points_net"] < 0], key=lambda x: x["points_net"]
        )
        examples[a["name"]] = {
            "short": short(a["name"]),
            "best_win": fmt_trade(wins[0]) if wins else None,
            "typical_loss": fmt_trade(losses[len(losses) // 2]) if losses else None,
        }

    families_out = []
    for fam in FAMILIES:
        members = []
        for m in fam["members"]:
            if m not in by_name:
                continue
            a = by_name[m]
            if a["rank"] > 25:
                continue
            live = a["live"]
            ytd = a.get("ytd_2026") or {}
            members.append(
                {
                    "name": m,
                    "short": short(m),
                    "rank": a["rank"],
                    "one_liner": DIFFS.get(
                        m,
                        f"Exit: {a['style']['exit_style']}. {a['ce_pct']}% CE / {a['pe_pct']}% PE.",
                    ),
                    "ce_pct": a["ce_pct"],
                    "pe_pct": a["pe_pct"],
                    "all_pts": live["total_points"],
                    "ytd_pts": ytd.get("total_points", 0),
                    "win_rate": live["win_rate"],
                    "avg_win": live["avg_win_pts"],
                    "avg_loss": live["avg_loss_pts"],
                    "trades_pm": round(
                        live["trades"] / max(len(a.get("monthly", {})), 1), 1
                    ),
                    "min_capital": a.get("min_capital"),
                }
            )
        if members:
            ranked_ytd = sorted(members, key=lambda x: -(x.get("ytd_pts") or 0))
            pairwise = [
                build_pairwise(ranked_ytd[i], ranked_ytd[i + 1], fam)
                for i in range(len(ranked_ytd) - 1)
            ]
            families_out.append(
                {
                    **fam,
                    "members": sorted(members, key=lambda x: x["rank"]),
                    "pairwise": pairwise,
                }
            )

    out = {
        "generated_at": date.today().isoformat(),
        "category": "Option Buying",
        "vs_credit_spread": "Credit spreads SELL premium (2 legs). Option buying PURCHASES single CE or PE — profits when premium rises.",
        "families": families_out,
        "calendars": calendars,
        "examples": examples,
        "top25": [{k: a[k] for k in a if k not in ("rows",)} for a in top25],
    }

    with open(OUT / "option_buying_diff.json", "w") as f:
        json.dump(out, f, indent=2)
    print(
        f"Wrote option_buying_diff.json — {len(calendars)} calendars, {len(families_out)} families"
    )


if __name__ == "__main__":
    main()
