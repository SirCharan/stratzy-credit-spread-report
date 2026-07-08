#!/usr/bin/env python3
"""Daily EOD "Movers" report for the Stratzy Almanac.

Ranks all Stratzy algos by 1-Month return (public API `oneMonthPnl`), takes the
top 25, and computes day-on-day and week-on-week movement in both rank and 1M%.
Also builds explicit **1-Day** and **1-Week leaderboards** and a "Your Book"
overlay from portfolio.json (ck's holdings).

Timeframe sources (all from `GET /api/web/algo/list`, public, no auth):
  1-Month  = `oneMonthPnl` (headline; the ranking spine).
  1-Week   = `sevenDayPnl` (headline; present for every algo).
  1-Day    = latest point of each algo's `performance` series (per-trading-session
             return). There is NO headline 1-day field, and algos trade at
             different cadences, so the 1-Day board only includes algos whose most
             recent session == the global-max session date (`day_board.as_of_date`);
             the rest simply didn't trade that session.

Pure public API — no Chrome/DHAN auth needed. Idioms copied from generate_universe.py.

Writes:
  movers/snapshots/YYYY-MM-DD.json   one per (trading) day (v2):
      {date, source, v:2, algos:[{id, rank, one_month_pnl, seven_day_pnl?, day_pnl?}]}
      (v1 files — rank+one_month_pnl only — still load; missing fields read as None.)
  movers/latest.json                 the report the SPA + Telegram bot read.

`ai_insight` is emitted here as None and filled by the daily Claude /schedule
routine (the LLM already in the loop). Contract:
  ai_insight: {
    generated_at, model,
    market_read: str,                                  # what's working now
    portfolio_actions: [{id, name, action, rationale}] # action in add|trim|hold|exit
    watchlist:         [{id, name, rationale}],
    risk_flags:        [str],
  }

On first run (no prior snapshots) it BACKFILLS the last ~10 weekdays from each
algo's rollingReturns30Day time-series, so 1M day/week deltas + sparklines are
populated immediately. (Backfilled days carry 1M only; 1D/1W deltas populate
forward as real v2 snapshots accumulate.)
"""

import datetime
import json
import os
import urllib.request

API = "https://stratzy.in/api/web/algo/list"
HERE = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(HERE, "movers", "snapshots")

TOP_N = 25
MOVERS_N = 8  # how many risers/fallers to list
SPARK_POINTS = 12  # trailing rolling-return points per algo sparkline
BACKFILL_DAYS = 10  # weekdays to reconstruct on first run
# rollingReturns30Day is oneMonthPnl annualized (×12); divide to get the %-scale
# that matches live oneMonthPnl so day/week PnL deltas are comparable. Ranking is
# unaffected (monotonic), so backfilled rank deltas stay valid regardless.
ROLL_FACTOR = 12.0


def fetch():
    req = urllib.request.Request(API, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["data"]


def num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def research_ids():
    """Ids flagged in_research in explore_data.json (the 50 deep-recomputed algos)."""
    try:
        ex = json.load(open(os.path.join(HERE, "explore_data.json")))
        return {a["id"] for a in ex.get("algos", []) if a.get("in_research")}
    except Exception:
        return set()


def rank_list(pairs):
    """pairs: list of (id, one_month_pnl, algo_score). Drop None pnl.
    Deterministic sort: pnl desc, then score desc, then id. Return {id: (rank, pnl)}."""
    clean = [
        (i, p, s if s is not None else -1e9) for (i, p, s) in pairs if p is not None
    ]
    clean.sort(key=lambda x: (-x[1], -x[2], x[0]))
    return {i: (rank, p) for rank, (i, p, _s) in enumerate(clean, start=1)}


# ---------- snapshots ----------
def snapshot_path(d):
    return os.path.join(SNAP_DIR, f"{d}.json")


def write_snapshot(date_str, source, ranked, extra=None):
    """ranked: {id:(rank,pnl)}. extra (optional): {id:{seven_day_pnl,day_pnl}} to persist
    the 1W/1D numbers for forward DoD/WoW deltas. Write compact v2 snapshot."""
    extra = extra or {}
    algos = []
    for i, (r, p) in ranked.items():
        row = {"id": i, "one_month_pnl": p, "rank": r}
        e = extra.get(i) or {}
        if e.get("seven_day_pnl") is not None:
            row["seven_day_pnl"] = e["seven_day_pnl"]
        if e.get("day_pnl") is not None:
            row["day_pnl"] = e["day_pnl"]
        algos.append(row)
    algos.sort(key=lambda a: a["rank"])
    out = {"date": date_str, "source": source, "v": 2, "algos": algos}
    json.dump(out, open(snapshot_path(date_str), "w"), separators=(",", ":"))


def load_snapshot(date_str):
    try:
        s = json.load(open(snapshot_path(date_str)))
        return {a["id"]: (a["rank"], a["one_month_pnl"]) for a in s["algos"]}
    except Exception:
        return None


def load_snapshot_full(date_str):
    """{id: {rank, one_month_pnl, seven_day_pnl, day_pnl}} or None. Missing (v1) fields -> None."""
    try:
        s = json.load(open(snapshot_path(date_str)))
        return {
            a["id"]: {
                "rank": a.get("rank"),
                "one_month_pnl": a.get("one_month_pnl"),
                "seven_day_pnl": a.get("seven_day_pnl"),
                "day_pnl": a.get("day_pnl"),
            }
            for a in s["algos"]
        }
    except Exception:
        return None


def existing_snapshot_dates():
    if not os.path.isdir(SNAP_DIR):
        return []
    ds = []
    for f in os.listdir(SNAP_DIR):
        if f.endswith(".json"):
            ds.append(f[:-5])
    return sorted(ds)


def parse_roll(series):
    """rollingReturns30Day dict {DD/MM/YYYY: pct} -> {date(): float}."""
    out = {}
    if not isinstance(series, dict):
        return out
    for k, v in series.items():
        try:
            d = datetime.datetime.strptime(k, "%d/%m/%Y").date()
            fv = float(v)
        except (ValueError, TypeError):
            continue
        out[d] = round(fv / ROLL_FACTOR, 2)  # annualized → 1-month %-scale
    return out


def parse_perf(series):
    """`performance` dict {DD/MM/YYYY: pct} -> sorted list [(date, pct)] (per-session return)."""
    out = []
    if not isinstance(series, dict):
        return out
    for k, v in series.items():
        try:
            d = datetime.datetime.strptime(k, "%d/%m/%Y").date()
            fv = float(v)
        except (ValueError, TypeError):
            continue
        out.append((d, round(fv, 2)))
    out.sort()
    return out


def weekdays_back(today, n):
    """The n weekdays strictly before `today`, most-recent first."""
    days, d = [], today
    while len(days) < n:
        d -= datetime.timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
    return days


def backfill(raw, today):
    """Reconstruct historical daily rankings from rollingReturns30Day; write any
    missing snapshot files for the last BACKFILL_DAYS weekdays. Idempotent."""
    rolls = {a["_id"]: parse_roll(a.get("rollingReturns30Day")) for a in raw}
    scores = {a["_id"]: num(a.get("algoScore")) for a in raw}
    for d in weekdays_back(today, BACKFILL_DAYS):
        ds = d.isoformat()
        if os.path.exists(snapshot_path(ds)):
            continue
        pairs = [(aid, r.get(d), scores.get(aid)) for aid, r in rolls.items() if d in r]
        if not pairs:
            continue
        write_snapshot(ds, "backfill", rank_list(pairs))


def main():
    os.makedirs(SNAP_DIR, exist_ok=True)
    raw = fetch()
    today = datetime.date.today()
    today_s = today.isoformat()

    by_id = {a["_id"]: a for a in raw}
    research = research_ids()

    # 1-Week = headline sevenDayPnl (every algo). 1-Day = latest `performance`
    # session return, but only for algos whose most-recent session == the global
    # max session date (others didn't trade that session).
    seven = {a["_id"]: num(a.get("sevenDayPnl")) for a in raw}
    latest_perf = {}  # id -> (date, pct) of its most recent session, or absent
    for a in raw:
        p = parse_perf(a.get("performance"))
        if p:
            latest_perf[a["_id"]] = p[-1]
    day_as_of = max((dp[0] for dp in latest_perf.values()), default=None)
    day_pnl = {
        aid: dp[1]
        for aid, dp in latest_perf.items()
        if day_as_of and dp[0] == day_as_of
    }

    # today's ranking from live oneMonthPnl (set for all algos)
    pairs = [
        (a["_id"], num(a.get("oneMonthPnl")), num(a.get("algoScore"))) for a in raw
    ]
    ranked_today = rank_list(pairs)
    extra = {
        aid: {"seven_day_pnl": seven.get(aid), "day_pnl": day_pnl.get(aid)}
        for aid in ranked_today
    }
    write_snapshot(today_s, "api", ranked_today, extra)

    # backfill prior days (first-run bootstrap), then pick prior/week snapshots
    backfill(raw, today)
    dates = [d for d in existing_snapshot_dates() if d < today_s]
    prior_date = dates[-1] if dates else None
    week_cut = (today - datetime.timedelta(days=7)).isoformat()
    week_candidates = [d for d in dates if d <= week_cut]
    week_date = (
        week_candidates[-1] if week_candidates else (dates[0] if dates else None)
    )

    prior = load_snapshot(prior_date) if prior_date else None
    week = load_snapshot(week_date) if week_date else None
    prior_full = load_snapshot_full(prior_date) if prior_date else None
    week_full = load_snapshot_full(week_date) if week_date else None

    def spark(aid):
        r = parse_roll(by_id[aid].get("rollingReturns30Day"))
        if not r:
            return None
        vals = [r[d] for d in sorted(r)][-SPARK_POINTS:]
        return vals if len(vals) >= 2 else None

    def enrich(aid):
        a = by_id[aid]
        rank, pnl = ranked_today[aid]
        d_rank = d_pnl = w_rank = w_pnl = None
        if prior and aid in prior:
            pr, pp = prior[aid]
            d_rank, d_pnl = pr - rank, round(pnl - pp, 2)
        if week and aid in week:
            wr, wp = week[aid]
            w_rank, w_pnl = wr - rank, round(pnl - wp, 2)
        return {
            "id": aid,
            "name": a.get("name"),
            "display_category": a.get("displayCategory"),
            "underlying": a.get("underlying"),
            "in_research": aid in research,
            "rank": rank,
            "one_month_pnl": pnl,
            "dod_rank_delta": d_rank,
            "dod_pnl_delta": d_pnl,
            "wow_rank_delta": w_rank,
            "wow_pnl_delta": w_pnl,
            "seven_day_pnl": num(a.get("sevenDayPnl")),
            "day_pnl": day_pnl.get(aid),
            "win_ratio": num(a.get("winRatio")),
            "spark": spark(aid),
        }

    ordered = sorted(ranked_today.items(), key=lambda kv: kv[1][0])  # by rank asc
    top = [enrich(aid) for aid, _ in ordered[:TOP_N]]

    # risers / fallers by day-on-day 1M% delta (across all ranked algos with a delta)
    all_rows = [enrich(aid) for aid, _ in ordered]
    with_d = [r for r in all_rows if r["dod_pnl_delta"] is not None]
    risers = sorted(with_d, key=lambda r: r["dod_pnl_delta"], reverse=True)[:MOVERS_N]
    fallers = sorted(with_d, key=lambda r: r["dod_pnl_delta"])[:MOVERS_N]

    def slim(r):
        return {
            "id": r["id"],
            "name": r["name"],
            "rank": r["rank"],
            "one_month_pnl": r["one_month_pnl"],
            "in_research": r["in_research"],
            "dod_pnl_delta": r["dod_pnl_delta"],
            "dod_rank_delta": r["dod_rank_delta"],
        }

    # entered / exited the top-25 vs prior snapshot
    today_top_ids = {r["id"] for r in top}
    entered, exited = [], []
    if prior:
        prior_top_ids = {i for i, (rk, _p) in prior.items() if rk <= TOP_N}
        for r in top:
            if r["id"] not in prior_top_ids:
                entered.append(
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "rank": r["rank"],
                        "one_month_pnl": r["one_month_pnl"],
                    }
                )
        for i in prior_top_ids - today_top_ids:
            exited.append(
                {
                    "id": i,
                    "name": by_id.get(i, {}).get("name", i),
                    "prior_rank": prior[i][0],
                }
            )
        exited.sort(key=lambda x: x["prior_rank"])

    # ----- portfolio "Your Book" overlay -----
    portfolio = None
    try:
        pf = json.load(open(os.path.join(HERE, "portfolio.json")))
        holdings = []
        total = sum(h["allocated"] for h in pf.get("holdings", []))
        wsum = 0.0
        for h in pf.get("holdings", []):
            aid = h["id"]
            row = enrich(aid) if aid in ranked_today else None
            pnl = row["one_month_pnl"] if row else None
            if pnl is not None:
                wsum += h["allocated"] * pnl
            slipping = bool(
                row
                and (
                    (row["seven_day_pnl"] or 0) < 0
                    or (row["dod_rank_delta"] is not None and row["dod_rank_delta"] < 0)
                )
            )
            holdings.append(
                {
                    "id": aid,
                    "name": h["name"],
                    "allocated": h["allocated"],
                    "weight_pct": round(100 * h["allocated"] / total, 1)
                    if total
                    else None,
                    "rank": row["rank"] if row else None,
                    "one_month_pnl": pnl,
                    "dod_rank_delta": row["dod_rank_delta"] if row else None,
                    "dod_pnl_delta": row["dod_pnl_delta"] if row else None,
                    "wow_rank_delta": row["wow_rank_delta"] if row else None,
                    "seven_day_pnl": row["seven_day_pnl"] if row else None,
                    "day_pnl": row["day_pnl"] if row else None,
                    "win_ratio": row["win_ratio"] if row else None,
                    "spark": row["spark"] if row else None,
                    "slipping": slipping,
                }
            )
        holdings.sort(key=lambda h: (h["rank"] is None, h["rank"] or 0))
        portfolio = {
            "total_allocated": total,
            "weighted_1m": round(wsum / total, 2) if total else None,
            "holdings": holdings,
            "flags": [h["name"] for h in holdings if h["slipping"]],
        }
    except FileNotFoundError:
        pass

    # ----- 1-Week board (headline sevenDayPnl) -----
    def week_row(aid):
        a = by_id[aid]
        s7 = seven.get(aid)
        row = {
            "id": aid,
            "name": a.get("name"),
            "display_category": a.get("displayCategory"),
            "in_research": aid in research,
            "seven_day_pnl": s7,
            "rank_1w": week_rank[aid],
            "dod_7d_delta": None,
            "wow_7d_delta": None,
        }
        if (
            s7 is not None
            and prior_full
            and prior_full.get(aid, {}).get("seven_day_pnl") is not None
        ):
            row["dod_7d_delta"] = round(s7 - prior_full[aid]["seven_day_pnl"], 2)
        if (
            s7 is not None
            and week_full
            and week_full.get(aid, {}).get("seven_day_pnl") is not None
        ):
            row["wow_7d_delta"] = round(s7 - week_full[aid]["seven_day_pnl"], 2)
        return row

    week_ids = sorted(
        (aid for aid in ranked_today if seven.get(aid) is not None),
        key=lambda aid: seven[aid],
        reverse=True,
    )
    week_rank = {aid: i for i, aid in enumerate(week_ids, start=1)}
    week_board = {
        "leaders": [week_row(aid) for aid in week_ids[:MOVERS_N]],
        "laggards": [week_row(aid) for aid in week_ids[::-1][:MOVERS_N]],
    }

    # ----- 1-Day board (latest performance-session return, same-session only) -----
    def day_row(aid):
        a = by_id[aid]
        dp = day_pnl.get(aid)
        row = {
            "id": aid,
            "name": a.get("name"),
            "display_category": a.get("displayCategory"),
            "in_research": aid in research,
            "day_pnl": dp,
            "rank_1d": day_rank[aid],
            "dod_1d_delta": None,
        }
        if (
            dp is not None
            and prior_full
            and prior_full.get(aid, {}).get("day_pnl") is not None
        ):
            row["dod_1d_delta"] = round(dp - prior_full[aid]["day_pnl"], 2)
        return row

    day_ids = sorted(day_pnl, key=lambda aid: day_pnl[aid], reverse=True)
    day_rank = {aid: i for i, aid in enumerate(day_ids, start=1)}
    day_board = {
        "as_of_date": day_as_of.isoformat() if day_as_of else None,
        "n_traded": len(day_pnl),
        "leaders": [day_row(aid) for aid in day_ids[:MOVERS_N]],
        "laggards": [day_row(aid) for aid in day_ids[::-1][:MOVERS_N]],
    }

    out = {
        "generated_at": today_s,
        "prior_date": prior_date,
        "week_ago_date": week_date,
        "total_algos": len(ranked_today),
        "narrative": "",  # filled by the scheduling agent
        "ai_insight": None,  # structured insight, filled by the /schedule routine (see docstring)
        "top": top,
        "day_board": day_board,
        "week_board": week_board,
        "risers": [slim(r) for r in risers],
        "fallers": [slim(r) for r in fallers],
        "entered": entered,
        "exited": exited,
        "portfolio": portfolio,
    }
    path = os.path.join(HERE, "movers", "latest.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    print(f"wrote {path}")
    print(
        f"  ranked {len(ranked_today)} algos; top{TOP_N} leader = {top[0]['name']} ({top[0]['one_month_pnl']}%)"
    )
    print(
        f"  prior={prior_date} week={week_date}  risers={len(risers)} fallers={len(fallers)} "
        f"entered={len(entered)} exited={len(exited)}"
    )
    if week_board["leaders"]:
        wl = week_board["leaders"][0]
        print(f"  1W leader = {wl['name']} ({wl['seven_day_pnl']}%)")
    if day_board["leaders"]:
        dl = day_board["leaders"][0]
        print(
            f"  1D board as_of={day_board['as_of_date']} n_traded={day_board['n_traded']} "
            f"leader = {dl['name']} ({dl['day_pnl']}%)"
        )
    if portfolio:
        print(
            f"  portfolio: {len(portfolio['holdings'])} holdings, weighted_1m={portfolio['weighted_1m']}%, "
            f"slipping={portfolio['flags']}"
        )


if __name__ == "__main__":
    main()
