#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decode the hall-of-fame submit flow: payload, and whether it charges.

The bundle contains POST /hall-of-fame/submit.  This pulls the surrounding code
so we can see the exact request body and any billing / free-run handling.
Read-only.
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

BASE = "https://gokujan.com"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")

r = urllib.request.Request(BASE + "/assets/index-B_EomOZP.js", headers={
    "User-Agent": "Mozilla/5.0", "Cookie": COOKIE,
    "Referer": BASE + "/hall-of-fame"})
js = urllib.request.urlopen(r, timeout=60).read().decode("utf-8", "replace")
print(f"bundle {len(js):,} bytes")
print()

for key in ("/hall-of-fame/submit", "/hall-of-fame/resolve",
            "/hall-of-fame/nominate", "/hall-of-fame/my-players"):
    hits = [m.start() for m in re.finditer(re.escape(key), js)]
    print("=" * 72)
    print(f"{key}   ({len(hits)} occurrence(s))")
    print("=" * 72)
    for i in hits[:2]:
        print(js[max(0, i - 1100):i + 700].replace("\\n", "\n"))
        print("-" * 72)
    print()

print("=" * 72)
print("does the hof submit path mention credits / free?")
print("=" * 72)
seg = None
i = js.find("/hall-of-fame/submit")
if i >= 0:
    seg = js[max(0, i - 3000):i + 3000]
for kw in ("credit", "free", "showcase", "billing", "cost", "charge"):
    n = seg.lower().count(kw) if seg else 0
    print(f"   {kw!r} in the submit region: {n}")
print()

print("=" * 72)
print("any i18n keys for the hof submit (labels the user saw)")
print("=" * 72)
for kw in ("hofSubmit", "hof.submit", "submitPaipu", "paipu", "模型", "複盤"):
    hits = [m.start() for m in re.finditer(re.escape(kw), js)]
    print(f"   {kw!r}: {len(hits)}")
