#!/usr/bin/env python3
"""Build correlations.json: pairwise daily-P&L correlation matrix (union calendar,
zero-filled = portfolio-risk correlation) + per-algo daily stats, for the ~50 deep
algos that have daily curves in equity_curves.json."""

import json, os, math, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_DAYS = 15  # need this many active days to be includable
TRADING_DAYS = 252


def main():
    eq = json.load(open(os.path.join(HERE, "equity_curves.json")))
    algos = eq["algos"]

    # per-algo day_pnl map (points) from all-time daily series
    series = {}
    meta = {}
    for a in algos:
        pts = (a.get("curves") or {}).get("daily_pts") or []
        m = {p["x"]: p.get("day_pnl", 0) or 0 for p in pts}
        if len(m) >= MIN_DAYS:
            series[a["id"]] = m
            meta[a["id"]] = {
                "id": a["id"],
                "short": a.get("short") or a.get("name"),
                "category": a.get("category"),
                "underlying": a.get("underlying"),
            }

    ids = list(series)
    # master calendar = union of all active days → consistent vector space
    cal = sorted({d for m in series.values() for d in m})
    vecs = {i: [series[i].get(d, 0.0) for d in cal] for i in ids}

    def stats(v):
        n = len(v)
        mean = sum(v) / n
        var = sum((x - mean) ** 2 for x in v) / n
        sd = math.sqrt(var)
        active = [x for x in v if x != 0]
        sharpe = round((mean / sd) * math.sqrt(TRADING_DAYS), 2) if sd > 0 else None
        return {
            "daily_mean": round(mean, 3),
            "daily_std": round(sd, 3),
            "sharpe": sharpe,
            "active_days": len(active),
            "total_pts": round(sum(v), 1),
        }

    for i in ids:
        meta[i].update(stats(vecs[i]))

    def corr(a, b):
        n = len(a)
        ma, mb = sum(a) / n, sum(b) / n
        va = sum((x - ma) ** 2 for x in a)
        vb = sum((x - mb) ** 2 for x in b)
        if va == 0 or vb == 0:
            return None
        cov = sum((a[k] - ma) * (b[k] - mb) for k in range(n))
        return round(cov / math.sqrt(va * vb), 3)

    matrix = {}
    for i in ids:
        row = {}
        for j in ids:
            row[j] = 1.0 if i == j else corr(vecs[i], vecs[j])
        matrix[i] = row

    out = {
        "generated_at": datetime.date.today().isoformat(),
        "method": "Pearson on daily P&L (points), union trading calendar, idle day = 0",
        "n_algos": len(ids),
        "calendar_days": len(cal),
        "algos": [meta[i] for i in ids],
        "matrix": matrix,
    }
    path = os.path.join(HERE, "correlations.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    print(f"wrote {path}: {len(ids)} algos, {len(cal)} calendar days")
    # quick sanity
    name = {i: meta[i]["short"] for i in ids}
    sample = ids[:1][0]
    pairs = sorted(
        ((matrix[sample][j], name[j]) for j in ids if j != sample),
        key=lambda t: (t[0] is None, t[0]),
    )
    print(f"least-correlated to {name[sample]!r}:", [(n, c) for c, n in pairs[:3]])


if __name__ == "__main__":
    main()
