#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check the account's task/review history for stuck or pending tasks.

Hypothesis being tested: the 429-on-submit with a never-clearing 900s window
might mean the account has many PENDING/unfinished analysis tasks, and the
submit endpoint rejects new runs while the queue is backed up.

GET /api/v2/review-history is read-only and cheap.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

API = "https://review.bigcoach.work/api/v2"
ORIGIN = "https://review.bigcoach.work"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def call(path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    r = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json",
        "Cookie": COOKIE, "Referer": "https://gokujan.com/hall-of-fame"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


for path in ("/review-history", "/tasks", "/hall-of-fame/my-runs",
             "/hall-of-fame/runs", "/dispatch"):
    st, txt = call(path)
    print(f"GET {path:24} -> HTTP {st} ({len(txt)} b)")
    if st == 200:
        try:
            d = json.loads(txt)
            s = json.dumps(d, ensure_ascii=False)
            print(f"    {s[:700]}")
        except Exception:
            print(f"    {txt[:400]}")
    print()