#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read the hall-of-fame page bundle to find what the submit form actually calls.

All the obvious /hall-of-fame/* submit paths returned 404, so the form must post
to an existing endpoint (likely POST /review) with extra fields.  The bundle
tells us exactly which.  Read-only; spends nothing.
"""
from __future__ import annotations

import os
import re
import sys
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = "https://review.bigcoach.work"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def get(url, accept="*/*"):
    r = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": accept, "Cookie": COOKIE, "Referer": BASE + "/hall-of-fame",
    })
    with urllib.request.urlopen(r, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


js = get(BASE + "/assets/index-B_EomOZP.js")
print(f"bundle: {len(js):,} bytes")
print()

print("=" * 70)
print("api paths referenced in the bundle")
print("=" * 70)
paths = sorted(set(re.findall(r'["\'`](/api/[A-Za-z0-9_\-/${}.]{2,60})["\'`]', js)))
for p in paths:
    print("   ", p)
print()

print("=" * 70)
print("strings around the hall-of-fame submit form")
print("=" * 70)
for key in ("hof-submit-paipu", "hof-submit-model-4p", "hof-submit"):
    i = js.find(key)
    print(f"--- {key!r}: {'found at ' + str(i) if i >= 0 else 'NOT FOUND'}")
    if i >= 0:
        print(js[max(0, i - 700):i + 900].replace("\\n", "\n"))
        print()
print()

print("=" * 70)
print("engine keys and free/credit wording")
print("=" * 70)
for key in ("rigel_14", "rigel_13", "名人堂免費", "review_standard_4p",
            "engineKeys", "analysisMode"):
    n = js.count(key)
    print(f"   {key!r} appears {n} time(s)")
    if n:
        i = js.find(key)
        print("      ...", js[max(0, i - 260):i + 260].replace("\\n", " ")[:520])
print()

print("=" * 70)
print("any 'free' / cost hints near the submit handler")
print("=" * 70)
for m in re.finditer(r'.{180}(免費|free|credit|積分|點數).{180}', js):
    seg = m.group(0)
    if any(k in seg for k in ("hof", "hall", "submit", "engine", "model")):
        print("   *", seg.replace("\\n", " ")[:420])
        print()
