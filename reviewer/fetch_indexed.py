#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch and save any analyses referenced by the harvest index.

Reading an existing task result is free (it does NOT consume the submit rate
budget), so this backfills any run whose payload was not saved -- e.g. the very
first validated run, or runs lost when a session was killed mid-fetch.

    python reviewer\\fetch_indexed.py
"""
from __future__ import annotations

import json
import os
import pathlib
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
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")

# taskIds confirmed to exist but not yet saved to disk
EXTRA = {"2020100913gm-0041-0000-388c8bcb": "d6c36f8c4e834cd9"}


def call(url, accept="application/json"):
    if url.startswith("/api/"):
        url = ORIGIN + url
    elif url.startswith("/"):
        url = API + url
    r = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": accept, "Cookie": COOKIE,
        "Referer": "https://gokujan.com/hall-of-fame"})
    try:
        with urllib.request.urlopen(r, timeout=90) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


def main() -> int:
    out = pathlib.Path("reviewer/out/hof_free").resolve()
    out.mkdir(parents=True, exist_ok=True)
    idx_p = out / "_index.json"
    index = json.loads(idx_p.read_text(encoding="utf-8")) if idx_p.is_file() else {}

    want = dict(EXTRA)
    for gid, rec in index.items():
        t = rec.get("taskId")
        if t and not (out / f"{gid}.json").is_file():
            want[gid] = t

    print(f"index entries      : {len(index)}")
    print(f"saved reviews      : {len(list(out.glob('*.json'))) - 1}")
    print(f"to fetch           : {len(want)}")
    print()

    got = 0
    for gid, task in want.items():
        st, txt = call(f"/tasks/{task}/result")
        if st != 200:
            print(f"  {gid}: result HTTP {st} {txt[:120]}")
            continue
        d = json.loads(txt).get("data") or {}
        ju = d.get("jsonUrl")
        if not ju:
            print(f"  {gid}: no jsonUrl yet (engine={d.get('modelName')!r})")
            continue
        s2, body = call(ju)
        if s2 != 200:
            print(f"  {gid}: data HTTP {s2}")
            continue
        rev = json.loads(body)
        rv = rev.get("review", {})
        kyo = rv.get("kyokus") or []
        ents = sum(len(k.get("entries") or []) for k in kyo)
        (out / f"{gid}.json").write_text(body, encoding="utf-8")
        index[gid] = {"taskId": task, "engine": d.get("modelName"),
                      "kyokus": len(kyo), "entries": ents}
        got += 1
        print(f"  saved {gid}.json  engine={d.get('modelName')!r} "
              f"kyokus={len(kyo)} entries={ents}")
        time.sleep(1)

    idx_p.write_text(json.dumps(index, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    print()
    print(f"fetched {got}; total reviews on disk: "
          f"{len(list(out.glob('*.json'))) - 1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
