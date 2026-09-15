#!/usr/bin/env python3
"""Download pastAdvices for ck's live Stratzy book (and optional CS/OB catalog).

Uses grokstratzybot session.env cookies. Never prints secrets.
Writes:
  /tmp/ck_live_algos.json
  /tmp/stratzy_fills/<id>.json          per-algo raw days
  /tmp/all_credit_spread_advices.json
  /tmp/all_option_buying_advices.json
  /tmp/all_other_advices.json
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOT = Path.home() / "claude" / "stratzygrokbot"
sys.path.insert(0, str(BOT))
import lib  # noqa: E402

OUT_DIR = Path("/tmp/stratzy_fills")
OUT_DIR.mkdir(parents=True, exist_ok=True)
ALGO_LIST = "https://stratzy.in/api/web/algo/list"


def to_iso(date_str: str) -> str:
    # Stratzy performance keys are D/M/YYYY or DD/MM/YYYY
    parts = date_str.split("/")
    if len(parts) != 3:
        return date_str
    d, m, y = parts
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


def public_algos() -> dict[str, dict]:
    code, body = lib.stratzy_get(ALGO_LIST)
    if code != 200 or not isinstance(body, dict):
        raise SystemExit(f"algo list http={code}")
    return {str(a["_id"]): a for a in body.get("data") or []}


def portfolio() -> dict[str, dict]:
    code, body = lib.stratzy_get("/api/algo/portfolio")
    if code != 200 or not isinstance(body, dict):
        raise SystemExit(f"portfolio http={code}")
    aa = body.get("activeAlgos") or {}
    if not isinstance(aa, dict):
        raise SystemExit("activeAlgos missing")
    return aa


def dates_for(pub: dict) -> list[tuple[str, str]]:
    perf = pub.get("performance") or {}
    keys = list(perf.keys()) if isinstance(perf, dict) else []
    out = []
    for k in keys:
        iso = to_iso(k)
        if len(iso) == 10:
            out.append((k, iso))
    out.sort(key=lambda x: x[1])
    return out


def fetch_day(advisor_id: str, iso: str) -> list:
    q = urllib.parse.urlencode(
        {
            "advisorId": advisor_id,
            "filter": "All",
            "chunk_size": "50",
            "offset": "0",
            "date": iso,
        }
    )
    code, body = lib.stratzy_get(f"/api/web/pastAdvices?{q}", timeout=40)
    if code in (401, 419):
        return None  # signal reauth
    if code != 200 or not isinstance(body, dict):
        return []
    return body.get("pastAdvices") or body.get("data") or []


def fetch_algo(aid: str, name: str, pub: dict, resume: dict) -> dict:
    path = OUT_DIR / f"{aid}.json"
    if path.exists() and not resume.get("force"):
        try:
            existing = json.loads(path.read_text())
            if existing.get("done"):
                print(f"  skip {name} (cached {existing.get('tradeCount', 0)} signals)")
                return existing
        except Exception:
            pass
    days = dates_for(pub)
    trades = []
    ok = fail = 0
    for i, (raw, iso) in enumerate(days):
        items = fetch_day(aid, iso)
        if items is None:
            print("UNAUTH mid-fetch")
            return {"done": False, "unauth": True, "algo": pub, "trades": trades}
        if items:
            trades.append({"date": raw, "iso": iso, "items": items})
            ok += 1
        else:
            fail += 1
        if (i + 1) % 40 == 0:
            print(f"    {name}: {i+1}/{len(days)} days")
        time.sleep(0.03)
    bundle = {
        "done": True,
        "algo": pub,
        "trades": trades,
        "ok": ok,
        "fail": fail,
        "dates": len(days),
        "tradeCount": sum(len(t["items"]) for t in trades),
    }
    path.write_text(json.dumps(bundle))
    print(f"  {name}: {bundle['tradeCount']} signals / {len(days)} dates")
    return bundle


def classify(pub: dict, name: str) -> str:
    cat = (pub.get("displayCategory") or pub.get("category") or "").lower()
    n = (name or "").lower()
    if "credit spread" in n or cat == "credit spread":
        return "cs"
    if cat in ("option buying", "options") or "fixedrr" in n.replace(" ", ""):
        return "ob"
    return "other"


def main() -> int:
    code, prof = lib.stratzy_get("/api/mobile/profile")
    if code != 200:
        print("session dead, run capture_session.py")
        return 1
    pub_map = public_algos()
    port = portfolio()
    print(f"public catalog {len(pub_map)}  book {len(port)}")

    live_rows = []
    for k, v in port.items():
        ad = v.get("algoData") if isinstance(v.get("algoData"), dict) else {}
        aid = str(v.get("advisorId") or k)
        live_rows.append(
            {
                "id": aid,
                "name": ad.get("name"),
                "category": ad.get("displayCategory") or ad.get("category"),
                "isDisabled": bool(v.get("isDisabled")),
                "isManual": v.get("isManual"),
                "automationEnabled": v.get("automationEnabled"),
                "amountDeployed": v.get("amountDeployed") or v.get("investedAmount"),
                "realizedPnl": v.get("realizedPnl"),
                "unrealizedPnL": v.get("unrealizedPnL"),
                "overallPnL": v.get("overallPnL"),
                "activeTrades": v.get("activeTrades"),
                "tradesExecuted": v.get("tradesExecuted"),
            }
        )
    Path("/tmp/ck_live_algos.json").write_text(json.dumps(live_rows, indent=2))
    enabled = [r for r in live_rows if not r["isDisabled"]]
    print(f"enabled {len(enabled)}  disabled {len(live_rows) - len(enabled)}")

    # fetch enabled first, then disabled (history still useful)
    order = [r for r in live_rows if not r["isDisabled"]] + [r for r in live_rows if r["isDisabled"]]
    dumps = {"cs": {}, "ob": {}, "other": {}}
    for r in order:
        pub = pub_map.get(r["id"]) or {"_id": r["id"], "name": r["name"], "displayCategory": r["category"], "performance": {}}
        name = r["name"] or pub.get("name") or r["id"]
        print(f"FETCH {name}")
        bundle = fetch_algo(r["id"], name, pub, {})
        if bundle.get("unauth"):
            return 2
        bucket = classify(pub, name)
        dumps[bucket][name] = bundle

    Path("/tmp/all_credit_spread_advices.json").write_text(json.dumps(dumps["cs"]))
    Path("/tmp/all_option_buying_advices.json").write_text(json.dumps(dumps["ob"]))
    Path("/tmp/all_other_advices.json").write_text(json.dumps(dumps["other"]))
    print(
        "DONE cs",
        len(dumps["cs"]),
        "ob",
        len(dumps["ob"]),
        "other",
        len(dumps["other"]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
