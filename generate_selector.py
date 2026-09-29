"""generate_selector.py -> selector.json

Decides which Stratzy algos ck should DEPLOY (subscribe @1 lot, Stratzy auto-executes on Dhan)
and which to COPY (allow-list for the 3x sell-leg top-up copier on the VM).

Inputs : regime_panel.json, correlations.json, explore_data.json, portfolio.json,
         nifty_vix_daily.json, iv_daily.json, data/trades_enriched.parquet (from regime_study.py)
Output : selector.json (repo root)

Rule tuning vs the brief (each justified in RULE_NOTES, written into selector.json):
  * thin cells (n<10) never count as "positive" (deploy trend test, copy VIX/IV test) and are
    ignored by the copy "no bucket worse than -0.5x avg" test - a 4-trade cell proves nothing.
  * "margin fits" = margin_per_lot <= Rs 1.2L, ck's standard per-algo allocation on auto algos.
  * copy also requires underlying NIFTY: the copier sizes in 65-unit NIFTY lots.
  * copy set and deploy shortlist are built greedily by score so pairwise |corr| stays under the
    cap (deploy: vs book + prior picks; copy: among copied picks, per brief).
  * naked risk = 3x the SELL legs' own P&L per 1-lot trade (copier adds 3x each SELL leg, no wing
    until 14:50), summed by exit day; worst day must be <= Rs 1L kill cap.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
THIN = 10
KILL_CAP = 100_000
COPY_X = 3
MARGIN_CAP = 120_000
NAKED_MARGIN_PER_LOT_EST = (
    135_000  # SPAN+exposure for one naked NIFTY 65-qty short, approx
)
DEPLOY_SHORTLIST_MAX = 5

RULES = {
    "deploy": {
        "min_trades": 30,
        "min_pf": 1.15,
        "min_calmar": 1.0,
        "min_positive_trend_buckets": 2,
        "max_abs_corr_to_book": 0.6,
        "max_margin_per_lot": MARGIN_CAP,
        "shortlist_max": DEPLOY_SHORTLIST_MAX,
    },
    "copy": {
        "structures": ["credit_spread", "strangle"],
        "underlying": "NIFTY",
        "min_trades": 60,
        "min_pf": 1.3,
        "min_calmar": 1.5,
        "trend_bucket_floor_x_avg": -0.5,
        "must_be_positive_in": ["vix_tercile", "iv_rank_tercile"],
        "max_abs_corr_within_copy_set": 0.5,
        "copy_x_sell_leg": COPY_X,
        "max_lots": 4,
        "naked_worst_day_max_rs": KILL_CAP,
        "ce_pe_skew_limit_lots": 7,
    },
    "notes": [
        "Thin cells (n<10) never count as positive and are skipped in the -0.5x floor test.",
        "margin fits = margin_per_lot <= Rs 1.2L (ck's standard per-algo allocation on auto algos).",
        "Copy requires NIFTY underlying: copier sizes in 65-unit NIFTY lots (TOPUP_LOT_UNITS=65).",
        "Deploy shortlist: greedy by score, |corr|<0.6 vs book AND vs earlier picks, max 5.",
        "Copy set: greedy by score, pairwise |corr|<0.5 among copied algos.",
        "Drop from book: fails both PF and Calmar gates, OR negative in 2+ non-thin trend buckets, OR Calmar < 0.5; other book algos missing a deploy gate go to watch_in_book.",
        "Naked risk = 3 x SELL-leg P&L per 1-lot trade, summed by exit day (pre-hedge, entry->exit "
        "prices only; intra-trade excursion not visible, so this UNDERSTATES true tail).",
        "Correlations: correlations.json (daily pts, 96 algos) where present, else same method "
        "recomputed from trades_enriched.parquet (flagged corr_source=parquet).",
    ],
}


def load(name):
    return json.loads((ROOT / name).read_text())


def r2(x, n=4):
    return (
        None
        if x is None or (isinstance(x, float) and math.isnan(x))
        else round(float(x), n)
    )


def tercile(v, lo, hi):
    if v is None:
        return "unknown"
    return "low" if v < lo else ("high" if v > hi else "mid")


def cell_ok(cell):
    return bool(cell) and cell["n"] >= THIN and (cell["avg_rs"] or 0) > 0


# ---------------------------------------------------------------- correlations
def build_corr(trades: pd.DataFrame, cj: dict):
    daily = (
        trades.assign(d=trades["exit_ts_ist"].str[:10])
        .groupby(["algo_id", "d"])["pnl_pts"]
        .sum()
    )
    wide = daily.unstack(0).fillna(0.0)
    pq = wide.corr()
    mx = cj["matrix"]

    def corr(a, b):
        if a == b:
            return 1.0, "self"
        if a in mx and b in mx[a] and mx[a][b] is not None:
            return mx[a][b], "correlations.json"
        if a in pq.index and b in pq.columns:
            v = pq.at[a, b]
            return (None, "none") if pd.isna(v) else (round(float(v), 3), "parquet")
        return None, "none"

    return corr


# ---------------------------------------------------------------- naked risk
def naked_daily(trades: pd.DataFrame) -> pd.DataFrame:
    """3x SELL-leg P&L per trade (Rs), with side counts for skew simulation."""
    rows = []
    for t in trades.itertuples():
        legs = json.loads(t.legs_json)
        sell_rs, ce, pe = 0.0, 0, 0
        for lg in legs:
            if lg["side"] != "SELL":
                continue
            sell_rs += (lg["entry_px"] - lg["exit_px"]) * lg["multiplier"]
            if lg["opt_type"] == "CE":
                ce += 1
            else:
                pe += 1
        rows.append(
            {
                "algo_id": t.algo_id,
                "exit_day": t.exit_ts_ist[:10],
                "entry_ts": t.entry_ts_ist,
                "exit_ts": t.exit_ts_ist,
                "naked_rs": COPY_X * sell_rs,
                "ce_lots": COPY_X * ce,
                "pe_lots": COPY_X * pe,
            }
        )
    return pd.DataFrame(rows)


def skew_sim(nk: pd.DataFrame, ids: list[str]) -> dict:
    """Replay copied entries in time order; count copies the <7 CE-PE lot skew gate would block."""
    sub = nk[nk.algo_id.isin(ids)].sort_values("entry_ts")
    open_pos, blocked, total, max_skew = [], 0, 0, 0
    for t in sub.itertuples():
        open_pos = [p for p in open_pos if p[0] > t.entry_ts]
        total += 1
        ce = sum(p[1] for p in open_pos) + t.ce_lots
        pe = sum(p[2] for p in open_pos) + t.pe_lots
        is_spread = (t.ce_lots == 0) != (t.pe_lots == 0)
        if is_spread and abs(ce - pe) >= 7:
            blocked += 1
            continue
        max_skew = max(max_skew, abs(ce - pe))
        open_pos.append((t.exit_ts, t.ce_lots, t.pe_lots))
    return {
        "entries": total,
        "blocked_by_skew": blocked,
        "blocked_pct": r2(100 * blocked / total, 2) if total else None,
        "max_skew_lots": max_skew,
    }


# ---------------------------------------------------------------- main
def main():
    panel, cj, explore, port = (
        load(f)
        for f in (
            "regime_panel.json",
            "correlations.json",
            "explore_data.json",
            "portfolio.json",
        )
    )
    nv, iv = load("nifty_vix_daily.json"), load("iv_daily.json")
    trades = pd.read_parquet(ROOT / "data/trades_enriched.parquet")
    corr = build_corr(trades, cj)
    nk = naked_daily(trades)
    underlying = (
        trades.groupby("algo_id")["underlying"].agg(lambda s: s.mode().iat[0]).to_dict()
    )
    ex = {a["id"]: a for a in explore["algos"]}

    # today's context = latest prior close (no same-day data); iv_daily may lag nifty_vix by days
    lo, hi = (
        panel["coverage"]["vix_tercile_1y"]["lo"],
        panel["coverage"]["vix_tercile_1y"]["hi"],
    )
    last_nv, last_iv = (
        nv[-1],
        next(r for r in reversed(iv) if r.get("iv_rank") is not None),
    )
    today = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "as_of_market_close": last_nv["date"],
        "iv_as_of": last_iv["date"],
        "trend": last_nv["trend_20d"],
        "vix": last_nv["vix"],
        "vix_chg_5d": r2(last_nv["vix_chg_5d"]),
        "vix_tercile": tercile(last_nv["vix"], lo, hi),
        "iv_rank": last_iv["iv_rank"],
        "iv_tercile": tercile(last_iv["iv_rank"], 33.33, 66.67),
        "atm_iv": r2(last_iv["atm_iv"]),
        "skew": r2(last_iv["skew"]),
        "skew_sign": "positive"
        if last_iv["skew"] > 0.005
        else ("negative" if last_iv["skew"] < -0.005 else "flat"),
        "nifty_weekly_expiry": last_iv["expiry"],
    }
    today["dte_bucket"] = (
        lambda d: "0" if d == 0 else "1" if d == 1 else "2" if d == 2 else "3+"
    )(
        (
            datetime.fromisoformat(last_iv["expiry"])
            - datetime.fromisoformat(today["date"])
        ).days
    )

    book_ids = [h["id"] for h in port["holdings"]]
    book = set(book_ids)
    D, C = RULES["deploy"], RULES["copy"]
    out = []
    for a in panel["algos"]:
        aid, cells = a["id"], a["cells"]
        others = [b for b in book_ids if b != aid]
        cvals = [(b, *corr(aid, b)) for b in others]
        cknown = [(b, v, s) for b, v, s in cvals if v is not None]
        worst = max(cknown, key=lambda x: abs(x[1]), default=(None, None, "none"))
        corr_to_book = worst[1]
        pf = a["pf"] if a["pf"] is not None else (99.0 if a.get("pf_inf") else 0.0)
        calmar = a["calmar"] or 0.0
        avg = a["avg_rs"] or 0.0
        trend = cells.get("trend_20d", {})
        tpos = sum(cell_ok(trend.get(b)) for b in ("bull", "side", "bear"))

        # fit today
        def tc(dim, key):
            c = cells.get(dim, {}).get(key)
            return (
                None
                if not c
                else {
                    "n": c["n"],
                    "wr": c["wr"],
                    "avg_rs": c["avg_rs"],
                    "thin": c["thin"],
                }
            )

        fit_cells = {
            "trend_20d": tc("trend_20d", today["trend"]),
            "vix_tercile": tc("vix_tercile", today["vix_tercile"]),
            "iv_rank_tercile": tc("iv_rank_tercile", today["iv_tercile"]),
            "skew_sign": tc("skew_sign", today["skew_sign"]),
            "dte_bucket": tc("dte_bucket", today["dte_bucket"]),
        }
        good = sum(
            1 for c in fit_cells.values() if c and not c["thin"] and c["avg_rs"] > 0
        )
        bad = sum(
            1 for c in fit_cells.values() if c and not c["thin"] and c["avg_rs"] <= 0
        )
        fit_verdict = (
            "favourable"
            if good >= 3 and bad == 0
            else ("unfavourable" if bad >= 2 else "mixed")
        )

        # ---- deploy
        dr, deligible = [], True
        checks = [
            (
                a["trades"] >= D["min_trades"],
                f"trades {a['trades']} {'>=' if a['trades'] >= D['min_trades'] else '<'} 30",
            ),
            (
                pf >= D["min_pf"],
                f"PF {pf:.2f} {'>=' if pf >= D['min_pf'] else '<'} 1.15",
            ),
            (
                calmar >= D["min_calmar"],
                f"Calmar {calmar:.2f} {'>=' if calmar >= D['min_calmar'] else '<'} 1.0",
            ),
            (tpos >= 2, f"positive in {tpos}/3 trend buckets (non-thin)"),
            (
                corr_to_book is None or abs(corr_to_book) < D["max_abs_corr_to_book"],
                f"max |corr| to book {corr_to_book if corr_to_book is not None else 'n/a'}"
                + (
                    f" ({(ex.get(worst[0]) or {}).get('short_name', worst[0])}, {worst[2]})"
                    if worst[0]
                    else ""
                ),
            ),
            (
                (a["margin_per_lot"] or 0) <= MARGIN_CAP,
                f"margin/lot Rs {round(a['margin_per_lot'] or 0):,}",
            ),
        ]
        for ok, msg in checks:
            deligible &= ok
            dr.append(("PASS " if ok else "FAIL ") + msg)
        if corr_to_book is None:
            dr.append("NOTE no overlapping correlation data")
        dscore = (
            min(max(calmar, 0), 8) / 8 * 40
            + min(max(pf - 1, 0), 1) * 30
            + tpos / 3 * 15
            + (1 - abs(corr_to_book or 0)) * 15
        )

        # ---- copy
        cr, celig = [], True
        u = underlying.get(aid)
        mine = nk[nk.algo_id == aid]
        day = mine.groupby("exit_day")["naked_rs"].sum()
        worst_day = r2(day.min(), 0) if len(day) else None
        p5_day = r2(day.quantile(0.05), 0) if len(day) else None
        floor = C["trend_bucket_floor_x_avg"] * avg
        bad_trend = [
            b
            for b, c in trend.items()
            if b != "unknown" and not c["thin"] and c["avg_rs"] < floor
        ]
        vix_c = cells.get("vix_tercile", {}).get(today["vix_tercile"])
        iv_c = cells.get("iv_rank_tercile", {}).get(today["iv_tercile"])
        cchecks = [
            (a["structure"] in C["structures"], f"structure {a['structure']}"),
            (u == "NIFTY", f"underlying {u}"),
            (a["trades"] >= C["min_trades"], f"trades {a['trades']} vs 60"),
            (pf >= C["min_pf"], f"PF {pf:.2f} vs 1.3"),
            (calmar >= C["min_calmar"], f"Calmar {calmar:.2f} vs 1.5"),
            (
                not bad_trend,
                "no trend bucket below -0.5x avg"
                if not bad_trend
                else f"trend buckets below -0.5x avg: {bad_trend}",
            ),
            (
                cell_ok(vix_c),
                f"today VIX tercile '{today['vix_tercile']}': "
                + (
                    f"n={vix_c['n']} avg_rs={vix_c['avg_rs']:.0f}"
                    if vix_c
                    else "no trades"
                ),
            ),
            (
                cell_ok(iv_c),
                f"today IV-rank tercile '{today['iv_tercile']}': "
                + (
                    f"n={iv_c['n']} avg_rs={iv_c['avg_rs']:.0f}"
                    if iv_c
                    else "no trades"
                ),
            ),
            (
                worst_day is not None and -worst_day <= KILL_CAP,
                f"naked 3x sell-leg worst day Rs {worst_day:,.0f} (p5 {p5_day:,.0f}) vs kill cap -1L"
                if worst_day is not None
                else "no naked history",
            ),
        ]
        for ok, msg in cchecks:
            celig &= ok
            cr.append(("PASS " if ok else "FAIL ") + msg)
        cscore = (
            (
                min(max(calmar, 0), 8) / 8 * 35
                + min(max(pf - 1, 0), 1) * 25
                + (good / 5) * 20
                + (1 - min(-(worst_day or 0) / KILL_CAP, 1)) * 20
            )
            if a["structure"] in C["structures"]
            else 0.0
        )

        out.append(
            {
                "id": aid,
                "name": a["name"],
                "category": a["category"],
                "structure": a["structure"],
                "bias": a["bias"],
                "underlying": u,
                "in_book": aid in book,
                "metrics": {
                    "trades": a["trades"],
                    "wr": a["wr"],
                    "pf": a["pf"],
                    "pf_inf": a.get("pf_inf", False),
                    "calmar": a["calmar"],
                    "avg_rs": a["avg_rs"],
                    "max_dd_rs": a["max_dd_rs"],
                    "margin_per_lot": a["margin_per_lot"],
                    "corr_to_book": corr_to_book,
                    "corr_source": worst[2],
                    "naked_worst_day_rs": worst_day,
                    "naked_p5_day_rs": p5_day,
                    "stratzy_1y_pct": (ex.get(aid) or {}).get("one_year_pnl_pct"),
                },
                "fit_today": {"verdict": fit_verdict, "cells": fit_cells},
                "deploy": {
                    "eligible": bool(deligible),
                    "score": r2(dscore, 1),
                    "reasons": dr,
                },
                "copy": {
                    "eligible": bool(celig),
                    "score": r2(cscore, 1),
                    "reasons": cr,
                },
                "rationale": "",
            }
        )

    # ---- deploy shortlist: greedy, |corr| < 0.6 vs book + earlier picks
    dep = []
    for x in sorted(
        (x for x in out if x["deploy"]["eligible"] and not x["in_book"]),
        key=lambda x: -x["deploy"]["score"],
    ):
        if len(dep) >= DEPLOY_SHORTLIST_MAX:
            break
        clash = [(p, corr(x["id"], p)[0]) for p in dep]
        clash = [
            (p, v)
            for p, v in clash
            if v is not None and abs(v) >= D["max_abs_corr_to_book"]
        ]
        if clash:
            x["deploy"]["reasons"].append(
                f"SKIP shortlist: |corr| {clash[0][1]} with pick {clash[0][0]}"
            )
            continue
        dep.append(x["id"])

    # ---- copy set: greedy, pairwise |corr| < 0.5 (book or not: copier reads ck's Dhan book,
    # so a copy pick that is NOT in the book is also a deploy prerequisite)
    cp = []
    for x in sorted(
        (x for x in out if x["copy"]["eligible"]), key=lambda x: -x["copy"]["score"]
    ):
        clash = [(p, corr(x["id"], p)[0]) for p in cp]
        clash = [
            (p, v)
            for p, v in clash
            if v is not None and abs(v) >= C["max_abs_corr_within_copy_set"]
        ]
        if clash:
            x["copy"]["eligible"] = False
            x["copy"]["reasons"].append(
                f"FAIL |corr| {clash[0][1]} with higher-scored copy pick {clash[0][0]}"
            )
            continue
        cp.append(x["id"])

    # ---- drop: book algos failing BOTH PF and Calmar gates, negative in 2+ trend buckets, or Calmar < 0.5
    # (1Y P&L under half its max DD: a repeat drawdown takes 2+ years to earn back)
    drop, watch = [], []
    for x in out:
        if not x["in_book"]:
            continue
        m = x["metrics"]
        pf = m["pf"] or 0
        weak_pf, weak_cal = pf < D["min_pf"], (m["calmar"] or 0) < D["min_calmar"]
        trend = next(a for a in panel["algos"] if a["id"] == x["id"])["cells"][
            "trend_20d"
        ]
        neg_trend = sum(1 for c in trend.values() if not c["thin"] and c["avg_rs"] < 0)
        if (weak_pf and weak_cal) or neg_trend >= 2 or (m["calmar"] or 0) < 0.5 * D["min_calmar"]:
            drop.append(x["id"])
        elif not x["deploy"]["eligible"]:
            watch.append(x["id"])

    # ---- pooled copy-set risk
    pooled = nk[nk.algo_id.isin(cp)].groupby("exit_day")["naked_rs"].sum()
    copy_set = {
        "pooled_naked_worst_day_rs": r2(pooled.min(), 0) if len(pooled) else None,
        "pooled_days_over_kill_cap": int((pooled < -KILL_CAP).sum())
        if len(pooled)
        else 0,
        "pooled_days": int(len(pooled)),
        "bias_mix": {
            b: sum(1 for x in out if x["id"] in cp and x["bias"] == b)
            for b in ("bearish", "bullish", "neutral")
        },
        "skew_replay": skew_sim(nk, cp),
        "extra_margin_est_rs_per_concurrent_copy": COPY_X * NAKED_MARGIN_PER_LOT_EST,
        "in_book": [i for i in cp if i in book],
        "needs_deploy_first": [i for i in cp if i not in book],
    }

    # ---- rationale strings
    for x in out:
        m, tag = x["metrics"], []
        if x["id"] in cp:
            tag.append(
                "COPY"
                + (
                    ""
                    if x["in_book"]
                    else " (deploy first: copier only sees Dhan fills)"
                )
            )
        if x["id"] in dep:
            tag.append("DEPLOY")
        if x["id"] in drop:
            tag.append("DROP from book")
        if x["id"] in watch:
            tag.append("WATCH (in book, misses a deploy gate)")
        fails = [r[5:] for r in x["deploy"]["reasons"] if r.startswith("FAIL")]
        x["rationale"] = (
            f"{' + '.join(tag) or 'pass'}: {m['trades']} trades, PF {m['pf']}, Calmar {m['calmar']}, "
            f"today {x['fit_today']['verdict']}"
            + (f"; deploy blockers: {'; '.join(fails)}" if fails else "")
        )

    out.sort(key=lambda x: (-(x["id"] in cp), -(x["id"] in dep), -x["deploy"]["score"]))
    res = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today": today,
        "rules": RULES,
        "source": {
            "regime_panel": panel["generated_at"],
            "correlations": cj["generated_at"],
            "portfolio": port["updated"],
            "trades": int(len(trades)),
        },
        "algos": out,
        "shortlist": {
            "deploy": dep,
            "copy": cp,
            "drop_from_book": drop,
            "watch_in_book": watch,
        },
        "copy_set": copy_set,
        "counts": {
            "deploy_eligible": sum(x["deploy"]["eligible"] for x in out),
            "copy_eligible": len(cp),
            "algos": len(out),
        },
    }
    (ROOT / "selector.json").write_text(json.dumps(res, indent=1, default=str))
    print("today", json.dumps(today))
    print("counts", res["counts"])
    names = {x["id"]: x["name"] for x in out}
    for k, v in res["shortlist"].items():
        print(k, [names[i] for i in v])
    print("copy_set", json.dumps(copy_set))


if __name__ == "__main__":
    main()
