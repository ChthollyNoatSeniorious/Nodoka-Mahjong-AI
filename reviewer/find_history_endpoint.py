#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find the endpoint that lists the account's past reviews/tasks.

If it exists, the user only needs to say "done" and every manual run can be
picked up automatically.  Read-only.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

API = "https://review.bigcoach.work/api/v2"
ORIGIN = "https://review.bigcoach.work"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def call(path):
    r = urllib.request.Request(API + path, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json",
        "Cookie": COOKIE, "Referer": "https://gokujan.com/"})
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


# 1) every api-ish literal near "review-history" in the bundle
r = urllib.request.Request("https://gokujan.com/assets/index-B_EomOZP.js",
                           headers={"User-Agent": "Mozilla/5.0", "Cookie": COOKIE})
js = urllib.request.urlopen(r, timeout=60).read().decode("utf-8", "replace")
i = js.find("review-history")
print("=== bundle context around 'review-history' ===")
if i >= 0:
    print(js[max(0, i - 500):i + 400].replace("\n", " "))
print()

# 2) probe plausible listing endpoints
print("=== endpoint probes ===")
for c in ("/reviews", "/reviews?page=1&pageSize=20", "/review?page=1",
          "/review/list", "/history", "/users/me/reviews",
          "/review-history?page=1&pageSize=10", "/tasks?page=1"):
    st, txt = call(c)
    ok = st == 200 and txt.strip() != '{"success":true,"data":[],"error":null,"message":null}'
    print(f"   {c:38} -> {st}{'  [HAS DATA]' if ok or st == 200 else ''}")
    if st == 200 and txt.startswith("{"):
        try:
            d = json.loads(txt)
            if isinstance(d.get("data"), list) and len(d.get("data") or []) > 0:
                print("      sample:", json.dumps(d["data"][0], ensure_ascii=False)[:250])
        except Exception:
            pass