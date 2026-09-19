#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe the bigcoach API for real: resolve a paipu and inspect the responses.

Reverse engineered from the SPA bundle:
    POST /api/v2/hall-of-fame/resolve   {paipu: url}
    POST /api/v2/hall-of-fame/submit    <payload>
    GET  /api/v2/tasks/{id}/progress
    GET  /api/v2/tasks/{id}/result      -> has jsonUrl / htmlUrl

IMPORTANT: the bundle contains the error code HOF_DAILY_RUNS_EXCEEDED, so
hall-of-fame submissions are rate limited per day.  This probe therefore only
calls `resolve` (read-only) by default, and requires --submit to go further.
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

TEST_URL = "https://tenhou.net/3/?log=2025031220gm-0009-0000-6233fed3&tw=0"


def call(method: str, path: str, body=None, accept="application/json"):
    url = path if path.startswith("http") else BASE + path
    headers = {"User-Agent": UA, "Accept": accept, "Cookie": COOKIE,
               "Accept-Language": "zh-TW,zh;q=0.9", "Referer":
               "https://review.bigcoach.work/hall-of-fame"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def show(label, status, text, limit=1600):
    print(f"===== {label}  ->  HTTP {status} =====")
    try:
        obj = json.loads(text)
        print(json.dumps(obj, ensure_ascii=False, indent=1)[:limit])
    except Exception:
        print(text[:limit])
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=TEST_URL)
    ap.add_argument("--submit", action="store_true",
                    help="ALSO submit (consumes daily hall-of-fame quota!)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--seat", type=int, default=0)
    args = ap.parse_args()

    if not COOKIE:
        print("set BIGCOACH_COOKIE", file=sys.stderr)
        return 2

    st, txt = call("POST", "/hall-of-fame/resolve", {"paipu": args.url})
    show("POST /hall-of-fame/resolve", st, txt)

    if not args.submit:
        print("(stopping here; pass --submit to continue and consume quota)")
        return 0

    payload = {"paipu": args.url, "playerId": args.seat}
    if args.model:
        payload["m"] = args.model
    st, txt = call("POST", "/hall-of-fame/submit", payload)
    show("POST /hall-of-fame/submit", st, txt)
    try:
        obj = json.loads(txt)
    except Exception:
        return 1
    d = obj.get("data") or obj
    task_id = d.get("taskId") or d.get("id") or d.get("task_id")
    print(f"task id: {task_id}")
    if not task_id:
        return 1

    import time
    for _ in range(20):
        st, txt = call("GET", f"/tasks/{task_id}/progress")
        print(f"progress: HTTP {st} {txt[:200]}")
        try:
            p = json.loads(txt).get("data") or {}
        except Exception:
            p = {}
        if str(p.get("status", "")).lower() in ("done", "finished", "success", "completed"):
            break
        time.sleep(5)

    st, txt = call("GET", f"/tasks/{task_id}/result")
    show("GET /tasks/{id}/result", st, txt, limit=2500)
    return 0


if __name__ == "__main__":
    sys.exit(main())
