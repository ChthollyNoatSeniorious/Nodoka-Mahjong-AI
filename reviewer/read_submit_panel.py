#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read SubmitPanel -- the actual hall-of-fame submit form.

Import chain:  /hall-of-fame -> HallOfFameHallView -> SubmitPanel-CkJBIMth.js

Final question: does submitting charge credits, or is it limited only by a daily
run count?  Read-only.
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
U = "https://gokujan.com/assets/SubmitPanel-CkJBIMth.js"
r = urllib.request.Request(U, headers={
    "User-Agent": "Mozilla/5.0", "Cookie": COOKIE,
    "Referer": "https://gokujan.com/hall-of-fame"})
js = urllib.request.urlopen(r, timeout=60).read().decode("utf-8", "replace")
print(f"SubmitPanel: {len(js):,} bytes")
print()

print("=" * 72)
print("A. billing mentions")
print("=" * 72)
for kw in ("credit", "免費", "free", "billing", "cost", "showcaseFree",
           "creditsOverride", "guard", "確認", "積分"):
    print(f"   {kw!r:18} {len(re.findall(re.escape(kw), js, re.I))}")
print()

print("=" * 72)
print("B. element ids the user pasted")
print("=" * 72)
for k in ("hof-submit-paipu", "hof-submit-model-4p", "hof-submit"):
    print(f"   {k!r}: {js.count(k)}")
print()

print("=" * 72)
print("C. imports (what it pulls in)")
print("=" * 72)
for m in re.finditer(r'import\{([^}]*)\}from"([^"]+)"', js):
    print(f"   from {m.group(2):40} {m.group(1)[:120]}")
print()

print("=" * 72)
print("D. i18n keys used (these are the labels you see)")
print("=" * 72)
keys = sorted(set(re.findall(r'"(hof\.[A-Za-z0-9_.]+)"', js)))
for k in keys:
    print("   ", k)
print()

print("=" * 72)
print("E. the submit payload")
print("=" * 72)
for kw in ("submit", "paipu", "model4p", "engineKey", "seat"):
    for m in list(re.finditer(kw, js, re.I))[:3]:
        i = m.start()
        print(f"  [{kw}]", js[max(0, i - 300):i + 380].replace("\n", " ")[:660])
        print()
