#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch an EXISTING bigcoach review by task id (no quota cost).

`POST /hall-of-fame/resolve` returns `cachedRuns[].taskId` for games that have
already been reviewed, which means we can download those reports without
burning the daily submission quota.

The SPA bundle shows the result payload carries `jsonUrl` and `htmlUrl`:
    function s_(e){ if(e?.jsonUrl) ... ; return e?.ui==="classic"&&e.htmlUrl ? ... }
so we read the report location straight from the result instead of guessing it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = "https://review.bigcoach.work/api/v2"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def call(path: str, accept="application/json"):
    url = path if path.startswith("http") else BASE + path
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": accept, "Cookie": COOKIE,
        "Referer": "https://review.bigcoach.work/"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--save", help="write the classic HTML here")
    args = ap.parse_args()

    st, txt = call(f"/tasks/{args.task_id}/result")
    print(f"GET /tasks/{args.task_id}/result -> HTTP {st}")
    try:
        obj = json.loads(txt)
        print(json.dumps(obj, ensure_ascii=False, indent=1)[:2200])
    except Exception:
        print(txt[:800])
        return 1

    data = obj.get("data") or obj
    # find any url-ish fields
    urls = {}
    def walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(o, list):
            for i, v in enumerate(o[:3]):
                walk(v, f"{path}[{i}]")
        elif isinstance(o, str) and ("url" in path.lower() or "Url" in path):
            urls[path] = o
    walk(data)
    print()
    print("=== url fields found ===")
    for k, v in urls.items():
        print(f"  {k} = {v}")

    if args.save and urls:
        # prefer an html url
        cand = [v for k, v in urls.items() if "html" in k.lower()] or list(urls.values())
        for u in cand:
            full = u if u.startswith("http") else "https://review.bigcoach.work" + u
            st2, body = call(full, accept="text/html,*/*")
            print(f"\nGET {full[:110]} -> HTTP {st2}, {len(body)} bytes")
            if st2 == 200 and len(body) > 5000:
                with open(args.save, "w", encoding="utf-8") as fh:
                    fh.write(body)
                print(f"saved -> {args.save}")
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())
