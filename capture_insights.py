#!/usr/bin/env python3
"""Capture the algo-insights Workflow output from its journal → judgments.json.

Reads a workflow transcript dir's journal.jsonl, collects the per-algo generate results
(judgment fields) and verify verdicts, applies any verify `corrected` overrides, and writes a
judgments.json for merge_algo_insights.py. Robust to the workflow return value not being surfaced.

Usage:  python3 capture_insights.py <workflow_transcript_dir> <out_judgments.json> [generated_at]
"""

import datetime
import json
import os
import sys


def main():
    if len(sys.argv) < 3:
        sys.exit(
            "usage: capture_insights.py <transcript_dir> <out.json> [generated_at]"
        )
    tdir, out_path = sys.argv[1], sys.argv[2]
    gen_at = sys.argv[3] if len(sys.argv) > 3 else datetime.date.today().isoformat()
    journal = os.path.join(tdir, "journal.jsonl")

    gen, ver = {}, {}
    for line in open(journal):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if o.get("type") != "result":
            continue
        r = o.get("result")
        if not isinstance(r, dict) or "id" not in r:
            continue
        if "style" in r:  # generate output
            gen[r["id"]] = r
        elif "ok" in r:  # verify verdict
            ver[r["id"]] = r

    algos, corrected = [], 0
    for aid, p in gen.items():
        prof = dict(p)
        v = ver.get(aid)
        if v and v.get("ok") is False and isinstance(v.get("corrected"), dict):
            prof.update(v["corrected"])
            corrected += 1
        algos.append({"id": aid, "profile": prof, "verdict": v})

    out = {
        "generated_at": gen_at,
        "model": "claude-sonnet-5 (workflow)",
        "algos": algos,
    }
    json.dump(out, open(out_path, "w"), separators=(",", ":"), ensure_ascii=False)
    print(f"captured {len(algos)} profiles ({corrected} verify-corrected) → {out_path}")
    unresolved = [aid for aid, v in ver.items() if v.get("ok") is False]
    if unresolved:
        print(f"  {len(unresolved)} flagged by verify: {unresolved[:5]}")


if __name__ == "__main__":
    main()
