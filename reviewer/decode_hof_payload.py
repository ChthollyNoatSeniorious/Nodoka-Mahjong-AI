#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final code check: what exactly does the hall-of-fame submit send, and is it
billed?

The submit region has no credit/billing strings, but let me confirm by reading
the payload ("paipu" appears 21 times in the bundle) and the mutation wiring.
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

COOKIE = os.environ.get("BIGCOACH_COOKIE", "")
r = urllib.request.Request("https://gokujan.com/assets/index-B_EomOZP.js",
                           headers={"User-Agent": "Mozilla/5.0", "Cookie": COOKIE})
js = urllib.request.urlopen(r, timeout=60).read().decode("utf-8", "replace")

print("=" * 72)
print("every 'paipu' occurrence, deduplicated by 200-char window")
print("=" * 72)
seen = set()
for m in re.finditer("paipu", js):
    i = m.start()
    seg = js[max(0, i - 260):i + 300]
    key = seg[:80]
    if key in seen:
        continue
    seen.add(key)
    print("  *", seg.replace("\n", " ")[:520])
    print()

print("=" * 72)
print("look for the hof submit mutation (what it sends)")
print("=" * 72)
for m in re.finditer(r"mutationFn", js):
    i = m.start()
    seg = js[max(0, i - 200):i + 500]
    if any(k in seg for k in ("hof", "HOF", "resolve", "submit", "playerPath",
                              "seat")):
        print("  *", seg.replace("\n", " ")[:650])
        print()

print("=" * 72)
print("strings mentioning 免費 / free that could belong to the hof form")
print("=" * 72)
for m in re.finditer(r"form\.model\.[a-zA-Z]+", js):
    pass
keys = sorted(set(re.findall(r'"(form\.model\.[a-zA-Z]+)"', js)))
print("   form.model.* keys:", keys)
print()
for m in re.finditer(r'"([a-zA-Z.]*hof[a-zA-Z.]*)"', js, re.I):
    print("   hof-ish key:", m.group(1))
