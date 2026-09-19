#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch review data for a list of review ids from review.bigcoach.work.

The /review/<id> page is a SPA shell; all data comes from public read APIs
(no cookie needed):

    GET /api/v2/tasks/<id>/result   -> {taskId, modelName, nplayer, jsonUrl, ui, ...}
    GET <jsonUrl>                   -> full review JSON:
        review.kyokus[].entries[]   (each decision: details[].action/.prob,
                                     state.tehai, actual, expected, actual_index)
        mjai_log[]                  (full mjai replay events)

Unqualified reviews (wrong engine, nplayer, missing jsonUrl, HTTP errors)
are reported but not fetched.  Output:

    reviewer/out/api_runs/<id>.json        full review JSON (only qualified)
    reviewer/out/api_runs/<id>.meta.json   result payload + fetch status
    reviewer/out/api_runs/_summary.json    aggregate counts/reasons

Rate limiting: 429 -> sleep retry-after once, then give up on that id.
Resumable: ids with an existing .json are skipped unless --refetch.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ORIGIN = "https://review.bigcoach.work"
API = ORIGIN + "/api/v2"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
OUT = pathlib.Path(__file__).resolve().parent / "out" / "api_runs"
ID_RE = re.compile(r"([0-9a-f]{16})")


def get_json(url: str, timeout: int = 120):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def fetch_data(json_url: str):
    """Follow /api/v2/tasks/<id>/data?token=... (may be absolute or relative)."""
    url = json_url if json_url.startswith("http") else ORIGIN + json_url
    st, body = get_json(url)
    if st != 200:
        raise RuntimeError(f"data HTTP {st}: {body[:150]}")
    return json.loads(body)


def fetch_one(rid: str, delay: float):
    """Returns (status, info) where info has keys for summary."""
    info = {"id": rid}
    try:
        st, body = get_json(f"{API}/tasks/{rid}/result")
    except urllib.error.HTTPError as e:
        info["status"] = f"result HTTP {e.code}"
        info["detail"] = e.read().decode("utf-8", "replace")[:200]
        return info
    except Exception as e:
        info["status"] = f"result ERR {e}"
        return info
    if st != 200:
        info["status"] = f"result HTTP {st}"
        info["detail"] = body[:200]
        return info
    try:
        res = json.loads(body)
    except Exception:
        info["status"] = "result not json"
        return info
    d = res.get("data") or {}
    info["modelName"] = d.get("modelName")
    info["nplayer"] = d.get("nplayer")
    info["ui"] = d.get("ui")
    info["jsonUrl"] = d.get("jsonUrl")
    info["paipuInfo"] = d.get("paipuInfo")
    jurl = d.get("jsonUrl")
    if info["modelName"] != "RIGEL 1.4":
        info["status"] = "reject engine"
        return info
    if info["nplayer"] != 4:
        info["status"] = "reject nplayer"
        return info
    if not jurl:
        info["status"] = "reject no jsonUrl"
        return info
    time.sleep(delay)
    try:
        data = fetch_data(jurl)
        info["status"] = "ok"
        info["bytes"] = len(json.dumps(data, ensure_ascii=False))
        info["kyokus"] = len(data.get("review", {}).get("kyokus", []))
        info["mjai_len"] = len(data.get("mjai_log") or [])
        info["entries"] = sum(len(k.get("entries", []))
                              for k in data.get("review", {}).get("kyokus", []))
        meta = {"id": rid, "modelName": info["modelName"],
                "nplayer": info["nplayer"],
                "jsonUrl": jurl,
                "raw_result": d}
        (OUT / f"{rid}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
        (OUT / f"{rid}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    except urllib.error.HTTPError as e:
        info["status"] = f"data HTTP {e.code}"
        info["detail"] = e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        info["status"] = f"data ERR {e}"
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", type=pathlib.Path,
                    default=pathlib.Path(__file__).resolve().parent /
                    "out" / "_txt_ids.txt")
    ap.add_argument("--out", type=pathlib.Path, default=OUT)
    ap.add_argument("--delay", type=float, default=2.5,
                    help="seconds between requests")
    ap.add_argument("--refetch", action="store_true")
    ap.add_argument("--max", type=int, help="only fetch first N ids")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    ids = []
    for line in args.list.read_text(encoding="utf-8").splitlines():
        m = ID_RE.search(line.strip())
        if m:
            ids.append(m.group(1))
    ids = list(dict.fromkeys(ids))
    if args.max:
        ids = ids[:args.max]
    print(f"{len(ids)} unique ids from {args.list.name}")

    def meta_stem(p: pathlib.Path) -> str:
        return p.name[: -len(".meta.json")]

    seen = set(meta_stem(p) for p in OUT.glob("*.meta.json")) if not args.refetch else set()
    remaining = [i for i in ids if i not in seen]
    print(f"already fetched: {len(ids)-len(remaining)}, to fetch: {len(remaining)}")

    summary = []
    n_ok = 0
    for i, rid in enumerate(remaining, 1):
        info = fetch_one(rid, args.delay)
        summary.append(info)
        if info.get("status") == "ok":
            n_ok += 1
            print(f"[{i}/{len(remaining)}] {rid} OK "
                  f"(entries={info['entries']} kyokus={info['kyokus']} "
                  f"mjai={info['mjai_len']})")
        else:
            print(f"[{i}/{len(remaining)}] {rid} {info.get('status')} "
                  f"{info.get('detail', '')[:80]}")
            if info.get("status", "").startswith("data HTTP 429") \
                    or info.get("status", "").startswith("result HTTP 429"):
                ra = 900
                print(f"  429 -> sleeping {ra}s, will retry this id once")
                time.sleep(ra)
                info2 = fetch_one(rid, args.delay)
                summary[-1] = info2
                if info2.get("status") == "ok":
                    n_ok += 1
                print(f"  retry: {info2.get('status')}")
        time.sleep(args.delay)

    (OUT / "_summary.json").write_text(
        json.dumps({"fetched": summary}, ensure_ascii=False), encoding="utf-8")

    from collections import Counter
    reasons = Counter(s.get("status", "?") for s in summary)
    print("\n=== summary ===")
    print(f"  ok            : {reasons.get('ok', 0)}")
    for k, v in reasons.most_common():
        if k != "ok":
            print(f"  {v:3}x {k}")
    print(f"  summary file  : {OUT / '_summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())