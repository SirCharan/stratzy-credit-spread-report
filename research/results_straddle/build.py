#!/usr/bin/env python3
"""Post-results short straddle board: data layer.

Writes earnings.json, trades.json, methodology.json next to this file.
Run:  python3 research/results_straddle/build.py [--refresh]
Reuses bs_price / implied_vol_bisect / download_bhav from ../../fetch_bhavcopy.py.
"""
import argparse, json, os, pickle, statistics, sys, time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
import pandas as pd
import requests
from urllib.parse import quote
from fetch_bhavcopy import (UA, RISK_FREE, download_bhav, implied_vol_bisect)

BHAV_DIR = os.path.join(ROOT, "data", "bhav")
PKL_DIR = os.path.join(BHAV_DIR, "sto_cache")
CACHE = os.path.join(HERE, "_cache")
TODAY = date(2026, 11, 4)              # overridden by --today / --rolling
WIN_FROM, WIN_TO = date(2026, 11, 4), date(2026, 11, 18)
ROLL_AHEAD = 10                        # rolling: results through today + 10 trading sessions
ROLL_BACK_DAYS = 12                    # rolling: look back so straddles exiting today are included
HIST_START = date(2024, 7, 8)          # UDiFF bhavcopy begins around here
HOLD = 5                               # exit = entry + 5 sessions
MIN_DTE_AT_EXIT = 7
PKL_VER = 2
VIDEO_BEST = {"POLYCAB", "ITC", "HDFCLIFE"}
VIDEO_WORST = {"MCX", "LUPIN", "SYNGENE"}
os.makedirs(PKL_DIR, exist_ok=True)
os.makedirs(CACHE, exist_ok=True)
NSE = "https://www.nseindia.com"


def d_(s, fmt="%d-%b-%Y"):
    return datetime.strptime(s, fmt).date()


# ------------------------------------------------------------------ NSE API
def nse_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json,text/plain,*/*",
                      "Accept-Language": "en-US,en;q=0.9", "Referer": NSE + "/"})
    try:
        s.get(NSE + "/", timeout=20)  # prime cookies (home may 403; API cookies still set)
    except Exception:
        pass
    return s


def nse_get(s, path, tries=4):
    last = None
    for i in range(tries):
        try:
            r = s.get(NSE + path, timeout=30)
            if r.status_code == 200 and r.text[:1] in "[{":
                return r.json()
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = repr(e)
        time.sleep(1.5 * (i + 1))
        try:
            s.get(NSE + "/", timeout=20)
        except Exception:
            pass
    raise RuntimeError(f"NSE {path[:80]} failed: {last}")


# ------------------------------------------------------------------ bhavcopy
def fetch_day(d):
    """Return True if bhavcopy exists for d (cached or downloaded)."""
    for attempt in range(2):
        data, _ = download_bhav(d, BHAV_DIR, 0.25)
        if data:
            return True
        time.sleep(0.5)
    return False


def parse_day(args):
    """Worker: zip -> compact per-symbol chains (3 nearest expiries, +-10% strikes) + ATM IV."""
    path, d = args
    pk = os.path.join(PKL_DIR, f"{d.strftime('%Y%m%d')}.v{PKL_VER}.pkl")
    if os.path.exists(pk):
        with open(pk, "rb") as f:
            return pickle.load(f)
    cols = ["FinInstrmTp", "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "ClsPric",
            "SttlmPric", "UndrlygPric", "NewBrdLotQty"]
    df = pd.read_csv(path, usecols=cols, low_memory=False)
    df = df[df.FinInstrmTp == "STO"].copy()
    px = df.ClsPric.where(df.ClsPric > 0, df.SttlmPric)
    df["px"] = px.where(px > 0)
    out = {"date": d, "sym": {}, "iv": {}}
    for sym, g in df.groupby("TckrSymb"):
        und = g.UndrlygPric[g.UndrlygPric > 0]
        if und.empty:
            continue
        spot = float(und.median())
        lot = int(g.NewBrdLotQty.dropna().iloc[0]) if g.NewBrdLotQty.notna().any() else None
        exps = sorted(e for e in g.XpryDt.unique() if d_(e, "%Y-%m-%d") >= d)[:3]
        chains = {}
        for e in exps:
            ge = g[(g.XpryDt == e) & (g.StrkPric.between(spot * 0.9, spot * 1.1))]
            ch = {}
            for r in ge.itertuples():
                ch.setdefault(float(r.StrkPric), {})[r.OptnTp] = (None if pd.isna(r.px) else float(r.px))
            chains[e] = ch
        out["sym"][sym] = {"spot": spot, "lot": lot, "exp": chains}
        # ATM IV series: nearest expiry with dte >= 7
        for e in exps:
            dte = (d_(e, "%Y-%m-%d") - d).days
            if dte < MIN_DTE_AT_EXIT:
                continue
            ch = chains[e]
            if not ch:
                break
            k = min(ch, key=lambda x: abs(x - spot))
            ce, pe = ch[k].get("CE"), ch[k].get("PE")
            if ce and pe:
                T = dte / 365.0
                a = implied_vol_bisect(ce, spot, k, T, RISK_FREE, True)
                b = implied_vol_bisect(pe, spot, k, T, RISK_FREE, False)
                if a and b:
                    out["iv"][sym] = (a + b) / 2
            break
    with open(pk, "wb") as f:
        pickle.dump(out, f)
    return out


# ------------------------------------------------------------------ helpers
def atm_strike(ch, spot):
    ks = [k for k, v in ch.items() if v.get("CE") and v.get("PE")]
    return min(ks, key=lambda x: abs(x - spot)) if ks else None


def choose_expiry(exps, entry, exit_):
    for e in exps:
        ed = d_(e, "%Y-%m-%d")
        if ed >= entry and (ed - exit_).days >= MIN_DTE_AT_EXIT:
            return e
    return None


def pctile(vals, cur):
    return round(100.0 * sum(1 for v in vals if v <= cur) / len(vals), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--rolling", action="store_true",
                    help="window = today .. today+10 trading sessions (plus a 12-day lookback for exits)")
    ap.add_argument("--today", help="YYYY-MM-DD override for 'today' (default: real date)")
    args = ap.parse_args()
    global TODAY, WIN_FROM, WIN_TO
    if args.today:
        TODAY = date.fromisoformat(args.today)
    elif args.rolling:
        TODAY = date.today()
    t0 = time.time()
    fetched = TODAY.isoformat()

    # ---- 1. bhavcopies for all weekdays from HIST_START
    days = []
    d = HIST_START
    while d <= TODAY:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    with ThreadPoolExecutor(min(args.workers, 6)) as ex:
        have = list(ex.map(fetch_day, days))
    bhav_days = [d for d, h in zip(days, have) if h]
    bhav_set = set(bhav_days)
    latest = bhav_days[-1]
    print(f"bhavcopies: {len(bhav_days)} trading days, latest {latest}", flush=True)

    # ---- 2. parse (parallel, pickled)
    jobs = [(os.path.join(BHAV_DIR, f"BhavCopy_NSE_FO_{d.strftime('%Y%m%d')}.csv.zip"), d) for d in bhav_days]
    with ProcessPoolExecutor(args.workers) as ex:
        parsed = dict(zip(bhav_days, ex.map(parse_day, jobs, chunksize=8)))
    print(f"parsed in {time.time()-t0:.0f}s", flush=True)
    fno = sorted(parsed[latest]["sym"])

    # ---- trading calendar
    s = nse_session()
    hol = nse_get(s, "/api/holiday-master?type=trading")
    fo_hol = {d_(x["tradingDate"]) for x in hol["FO"]}

    def is_trading(d):
        if d <= latest:
            return d in bhav_set
        return d.weekday() < 5 and d not in fo_hol

    def add_sessions(d, n):
        while n > 0:
            d += timedelta(days=1)
            if is_trading(d):
                n -= 1
        return d

    def next_session(d):
        return add_sessions(d, 1)

    if args.rolling:
        WIN_FROM = TODAY - timedelta(days=ROLL_BACK_DAYS)
        WIN_TO = add_sessions(TODAY, ROLL_AHEAD)
        print(f"rolling window {WIN_FROM} .. {WIN_TO}", flush=True)

    # ---- 3. results calendar
    qs = f"from_date={WIN_FROM:%d-%m-%Y}&to_date={WIN_TO:%d-%m-%Y}"
    bm = nse_get(s, f"/api/corporate-board-meetings?index=equities&{qs}")
    ec = nse_get(s, f"/api/event-calendar?index=equities&{qs}")
    cal = {}  # symbol -> dict
    for r in bm:
        if "financial results" not in (r.get("bm_purpose") or "").lower():
            continue
        dt = d_(r["bm_date"])
        if not (WIN_FROM <= dt <= WIN_TO):
            continue
        prev = cal.get(r["bm_symbol"])
        if prev is None or r.get("bm_timestamp", "") > prev["_ts"]:
            cal[r["bm_symbol"]] = {"company": r.get("sm_name"), "results_date": dt, "_ts": r.get("bm_timestamp", ""),
                                   "src": "corporate-board-meetings"}
    n_bm = len(cal)
    for r in ec:
        if "financial results" not in (r.get("purpose") or "").lower():
            continue
        dt = d_(r["date"])
        if WIN_FROM <= dt <= WIN_TO and r["symbol"] not in cal:
            cal[r["symbol"]] = {"company": r.get("company"), "results_date": dt, "_ts": "", "src": "event-calendar"}
    all_in_window = len(cal)
    earnings = []
    for sym in fno:
        c = cal.get(sym)
        if not c:
            continue
        rd = c["results_date"]
        entry = next_session(rd)   # timing unknown from NSE feeds -> conservative next session
        earnings.append({"symbol": sym, "company": c["company"], "results_date": rd.isoformat(),
                         "timing": "unknown", "entry_date": entry.isoformat(),
                         "exit_date": add_sessions(entry, HOLD).isoformat(), "source": c["src"]})
    earnings.sort(key=lambda e: (e["results_date"], e["symbol"]))
    print(f"window results (all NSE): {all_in_window} (board-meetings {n_bm}); F&O: {len(earnings)}", flush=True)

    # ---- 4. history: board-meeting dates per name
    def hist_dates(sym):
        fp = os.path.join(CACHE, f"bm_{sym}.json")
        if os.path.exists(fp) and not args.refresh:
            with open(fp) as f:
                rows = json.load(f)
        else:
            time.sleep(0.15)
            rows = nse_get(s, f"/api/corporate-board-meetings?index=equities&symbol={quote(sym)}"
                              f"&from_date=01-07-2024&to_date={TODAY:%d-%m-%Y}")
            with open(fp, "w") as f:
                json.dump(rows, f)
        ds = sorted({d_(r["bm_date"]) for r in rows
                     if "financial results" in (r.get("bm_purpose") or "").lower()
                     and HIST_START <= d_(r["bm_date"]) < TODAY - timedelta(days=9)})
        # collapse reschedules: dates within 30 days of a later one -> keep the later
        keep = [x for i, x in enumerate(ds) if i == len(ds) - 1 or (ds[i + 1] - x).days >= 30]
        return keep[-8:]

    names = [e["symbol"] for e in earnings]
    hist_err = {}

    def safe_hd(sym):
        try:
            return sym, hist_dates(sym)
        except Exception as e:
            hist_err[sym] = str(e)
            return sym, []
    with ThreadPoolExecutor(4) as ex:
        hd = dict(ex.map(safe_hd, names))

    def replay(sym, rd):
        """Return (event dict, None) or (None, skip_reason)."""
        entry = next_session(rd)
        if entry not in bhav_set:
            return None, "entry_no_bhav"
        exit_ = add_sessions(entry, HOLD)
        if exit_ not in bhav_set:
            return None, "exit_no_bhav"
        pe_, px_ = parsed[entry]["sym"].get(sym), parsed[exit_]["sym"].get(sym)
        if not pe_ or not px_:
            return None, "symbol_missing"
        exp = choose_expiry(sorted(pe_["exp"]), entry, exit_)
        if not exp:
            return None, "no_expiry"
        k = atm_strike(pe_["exp"][exp], pe_["spot"])
        if k is None:
            return None, "no_atm_quotes"
        ex_ch = px_["exp"].get(exp, {}).get(k)
        if not ex_ch or not ex_ch.get("CE") or not ex_ch.get("PE"):
            return None, "no_exit_quotes"
        ec_ = pe_["exp"][exp][k]
        credit, cost = ec_["CE"] + ec_["PE"], ex_ch["CE"] + ex_ch["PE"]
        return {"results_date": rd.isoformat(), "entry_date": entry.isoformat(), "exit_date": exit_.isoformat(),
                "expiry": exp, "strike": k, "spot_entry": round(pe_["spot"], 2),
                "entry_premium": round(credit, 2), "exit_premium": round(cost, 2),
                "ret_pct": round(100 * (credit - cost) / credit, 2)}, None

    # ---- 5. trade cards
    snap = parsed[latest]
    ivhist = {}
    for d in bhav_days:
        for sym, v in parsed[d]["iv"].items():
            ivhist.setdefault(sym, []).append((d, v))
    trades, skip_counts = [], {}
    for e in earnings:
        sym = e["symbol"]
        entry, exit_ = d_(e["entry_date"], "%Y-%m-%d"), d_(e["exit_date"], "%Y-%m-%d")
        row = dict(e)
        sd = snap["sym"].get(sym)
        exp = choose_expiry(sorted(sd["exp"]), entry, exit_) if sd else None
        k = atm_strike(sd["exp"][exp], sd["spot"]) if exp else None
        if k is None:
            row.update({"card": False, "card_reason": "no expiry/ATM quotes in latest bhavcopy"})
            trades.append(row)
            continue
        q = sd["exp"][exp][k]
        prem = q["CE"] + q["PE"]
        dte = (d_(exp, "%Y-%m-%d") - latest).days
        T = dte / 365.0
        iv = None
        a = implied_vol_bisect(q["CE"], sd["spot"], k, T, RISK_FREE, True)
        b = implied_vol_bisect(q["PE"], sd["spot"], k, T, RISK_FREE, False)
        if a and b:
            iv = round(100 * (a + b) / 2, 2)
        series = [v for dd, v in ivhist.get(sym, []) if latest - timedelta(days=365) <= dd < latest]
        cur = ivhist.get(sym, [(None, None)])[-1][1] if ivhist.get(sym) and ivhist[sym][-1][0] == latest else None
        iv_rank = pctile(series, cur) if cur is not None and len(series) >= 60 else None
        evs, skips = [], {}
        for rd in hd.get(sym, []):
            ev, why = replay(sym, rd)
            if ev:
                evs.append(ev)
            else:
                skips[why] = skips.get(why, 0) + 1
                skip_counts[why] = skip_counts.get(why, 0) + 1
        rets = [x["ret_pct"] for x in evs]
        hist = {"n": len(rets), "events_found": len(hd.get(sym, [])), "skipped": sum(skips.values()),
                "skip_reasons": skips,
                "win_rate": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1) if rets else None,
                "median": round(statistics.median(rets), 2) if rets else None,
                "mean": round(statistics.mean(rets), 2) if rets else None,
                "worst": round(min(rets), 2) if rets else None, "events": evs}
        flags = []
        if hist["worst"] is not None and hist["worst"] <= -150:
            flags.append("worst_case")
        if sym in VIDEO_BEST:
            flags.append("video_best")
        if sym in VIDEO_WORST:
            flags.append("video_worst")
        if hist["n"] < 4:
            flags.append("low_history")
        row.update({"card": True, "bhav_date": latest.isoformat(), "spot": round(sd["spot"], 2), "lot_size": sd["lot"],
                    "expiry": exp, "dte_at_bhav": dte, "dte_at_exit": (d_(exp, "%Y-%m-%d") - exit_).days,
                    "atm_strike": k, "ce_premium": q["CE"], "pe_premium": q["PE"], "total_premium": round(prem, 2),
                    "credit_per_lot": round(prem * sd["lot"], 2) if sd["lot"] else None,
                    "atm_iv": iv, "iv_rank_1y": iv_rank,
                    "upper_breakeven": round(k + prem, 2), "lower_breakeven": round(k - prem, 2),
                    "breakeven_move_pct": round(100 * prem / sd["spot"], 2), "history": hist, "flags": flags})
        trades.append(row)

    def sk(r):
        h = r.get("history") or {}
        return (r.get("card", False),
                h.get("median") if h.get("median") is not None else -1e9,
                r.get("iv_rank_1y") if r.get("iv_rank_1y") is not None else -1,
                r.get("credit_per_lot") or 0)
    trades.sort(key=sk, reverse=True)
    for i, r in enumerate(trades, 1):
        r["rank"] = i

    # ---- 6. outputs
    def dump(name, obj):
        with open(os.path.join(HERE, name), "w") as f:
            json.dump(obj, f, indent=1, default=str)
    dump("earnings.json", {"generated": fetched, "today": TODAY.isoformat(), "window": [WIN_FROM.isoformat(), WIN_TO.isoformat()],
                           "all_nse_results_in_window": all_in_window, "fno_in_window": len(earnings),
                           "fno_universe": len(fno), "calendar_source": "NSE /api/corporate-board-meetings (+ /api/event-calendar fallback)",
                           "holidays_in_range": sorted(h.isoformat() for h in fo_hol if TODAY - timedelta(days=15) <= h <= WIN_TO + timedelta(days=30)),
                           "earnings": earnings})
    dump("trades.json", {"generated": fetched, "bhav_date": latest.isoformat(), "count": len(trades),
                         "cards": sum(1 for r in trades if r.get("card")),
                         "history_ge4": sum(1 for r in trades if r.get("card") and r["history"]["n"] >= 4),
                         "skip_reasons_total": skip_counts, "hist_fetch_errors": hist_err, "trades": trades})
    dump("methodology.json", {
        "generated": fetched,
        "video": {"title": "We Backtested Selling Options After Earnings (Zerodha)",
                  "universe": "209 NSE F&O stocks, Oct 2021 to Aug 2026",
                  "rule": "Sell naked ATM straddle (ATM CE + ATM PE) at 9:20 a.m. on the first trading session after the results announcement; exit 5 trading days later.",
                  "stats_day5_exit": {"win_rate_pct": 70.58, "avg_return_pct_of_premium": 6.44, "median_return_pct_of_premium": 13.65},
                  "named_best_by_median": ["Polycab", "ITC", "HDFC Life"], "named_worst": ["MCX", "Lupin", "Syngene"]},
        "this_board": {
            "entry": "First NSE session after results_date (timing pre/post unknown in NSE feeds, so always next session; a pre-market announcement would really allow same-day entry).",
            "exit": f"Entry + {HOLD} trading sessions (entry day = day 0), using NSE FO holiday list.",
            "expiry": f"Nearest monthly stock expiry on/after entry; rolled to next monthly if < {MIN_DTE_AT_EXIT} calendar DTE would remain at exit.",
            "strike": "Listed strike nearest the underlying close (UndrlygPric) of the bhavcopy.",
            "return_pct": "(entry credit - exit cost) / entry credit * 100, per share, same strikes, no costs/slippage/margin financing.",
            "iv": "Black-Scholes bisection IV (r=6.5%, ACT/365) averaged over ATM CE and PE, at the card expiry.",
            "iv_rank_1y": "Percentile of latest ATM IV (nearest expiry with >=7 DTE) among prior 365 days of the same series; null if < 60 observations.",
            "history": "Last up to 8 past 'Financial Results' board-meeting dates since 2024-07 per name (reschedules within 30 days collapsed to the later date). Events lacking bhavcopy/strike data are skipped and counted.",
            "ranking": "History median desc, then IV rank desc, then credit per lot desc. No names dropped.",
            "flags": {"worst_case": "history worst <= -150%", "video_best/video_worst": "six names cited in the video", "low_history": "n < 4"}},
        "approximations": [
            "EOD bhavcopy close (ClsPric, falling back to SttlmPric) stands in for the 9:20 a.m. fill; real entry prices and spot at 9:20 differ, often materially on results gaps.",
            "ATM chosen from the entry-day close, not the 9:20 spot.",
            "Results timing (pre/post market) is not in NSE board-meeting feeds; next session is assumed, so same-day pre-market entries are not modelled.",
            "History uses fewer than the video's 4+ years (UDiFF bhavcopy only from mid-2024) and at most 8 events per name.",
            "Trade cards use the latest available bhavcopy; live premiums on entry day will differ.",
            "Illiquid strikes may show stale closes; no bid/ask spread, brokerage, STT or margin cost modelled."],
        "sources": [
            {"what": "Results calendar and history", "url": NSE + "/api/corporate-board-meetings", "fallback": NSE + "/api/event-calendar", "fetched": fetched},
            {"what": "Holiday list", "url": NSE + "/api/holiday-master?type=trading", "fetched": fetched},
            {"what": "F&O UDiFF bhavcopy (STO/STF, lot size, spot)", "url": "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip", "latest_used": latest.isoformat(), "fetched": fetched},
            {"what": "Video transcript", "path": "/Users/ck/.claude/jobs/9c58b135/tmp/vid.en.vtt"}],
        "disclaimer": "Research illustration only, not investment advice. A naked short straddle has unlimited loss on the call side and very large loss on the put side; results gaps can cost many times the premium collected, and margin requirements are large. Past backtests do not predict future results."})

    # ---- 7. asserts
    for r in trades:
        rd, en = d_(r["results_date"], "%Y-%m-%d"), d_(r["entry_date"], "%Y-%m-%d")
        assert is_trading(en), f"{r['symbol']} entry {en} not a trading day"
        assert en > rd or (en == rd and r["timing"] == "pre"), f"{r['symbol']} entry not after results"
        assert d_(r["exit_date"], "%Y-%m-%d") == add_sessions(en, HOLD)
        if not r.get("card"):
            continue
        ch = snap["sym"][r["symbol"]]["exp"][r["expiry"]]
        assert r["atm_strike"] in ch, f"{r['symbol']} strike missing in chain"
        assert ch[r["atm_strike"]].get("CE") and ch[r["atm_strike"]].get("PE")
        assert r["ce_premium"] > 0 and r["pe_premium"] > 0 and r["total_premium"] > 0
        assert r["dte_at_exit"] >= MIN_DTE_AT_EXIT
        for ev in r["history"]["events"]:
            hch = parsed[d_(ev["entry_date"], "%Y-%m-%d")]["sym"][r["symbol"]]["exp"][ev["expiry"]]
            assert ev["strike"] in hch and ev["entry_premium"] > 0 and ev["exit_premium"] >= 0
            assert d_(ev["entry_date"], "%Y-%m-%d") > d_(ev["results_date"], "%Y-%m-%d")
    print(f"ASSERTS PASSED. cards={sum(1 for r in trades if r.get('card'))}/{len(trades)}; "
          f"hist>=4={sum(1 for r in trades if r.get('card') and r['history']['n']>=4)}; "
          f"skips={skip_counts}; errs={len(hist_err)}; {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
