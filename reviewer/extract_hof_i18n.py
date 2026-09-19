#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pull the hall-of-fame UI strings from the locales bundle.

These are the exact labels the user sees, so they settle two things:
  * what the submit form requires, and
  * whether the page ever mentions credits for the hall-of-fame flow, or only a
    daily run limit (HOF_DAILY_RUNS_EXCEEDED).
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

COOKIE = os.environ.get("BIGCOACH_COOKIE", "")
r = urllib.request.Request("https://gokujan.com/assets/locales-LRQV2N5c.js",
                           headers={"User-Agent": "Mozilla/5.0", "Cookie": COOKIE})
js = urllib.request.urlopen(r, timeout=60).read().decode("utf-8", "replace")
print(f"locales bundle: {len(js):,} bytes")
print()

kv = {}
for m in re.finditer(r'"([A-Za-z0-9_.]+)"\s*:\s*"((?:[^"\\]|\\.){2,300})"', js):
    kv.setdefault(m.group(1), m.group(2))

def show(prefix, limit=60):
    keys = [k for k in kv if k.lower().startswith(prefix.lower())]
    print(f"=== keys starting with {prefix!r}: {len(keys)} ===")
    for k in sorted(keys)[:limit]:
        v = kv[k]
        try:
            v = v.encode().decode("unicode_escape")
        except Exception:
            pass
        print(f"   {k:58} {v[:150]}")
    print()

show("hof", 80)
show("hallOfFame", 40)

print("=== any string mentioning credits/free near hall of fame ===")
for k, v in kv.items():
    try:
        vv = v.encode().decode("unicode_escape")
    except Exception:
        vv = v
    if any(w in k.lower() for w in ("hof", "halloffame", "submit", "nominate")):
        if any(w in vv for w in ("積分", "免費", "點數", "credit", "free",
                                 "每日", "次數", "上限", "daily")):
            print(f"   {k:58} {vv[:170]}")
print()

print("=== global strings about daily limits / free ===")
for k, v in kv.items():
    try:
        vv = v.encode().decode("unicode_escape")
    except Exception:
        vv = v
    if any(w in vv for w in ("每日", "免費", "daily", "free of charge")) \
       and len(vv) < 200:
        print(f"   {k:58} {vv[:170]}")
