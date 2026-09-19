#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read the hall-of-fame page chunk: submit payload + whether it is billed.

Route:  /hall-of-fame -> S0 -> import("./HallOfFameHallView-DY7DM9lo.js")

This is the last unknown: does the submit charge credits, or is it limited only
by a daily run count (HOF_DAILY_RUNS_EXCEEDED)?  Read-only.
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
CHUNK = "https://gokujan.com/assets/HallOfFameHallView-DY7DM9lo.js"

r = urllib.request.Request(CHUNK, headers={
    "User-Agent": "Mozilla/5.0", "Cookie": COOKIE,
    "Referer": "https://gokujan.com/hall-of-fame"})
js = urllib.request.urlopen(r, timeout=60).read().decode("utf-8", "replace")
print(f"chunk: {len(js):,} bytes")
print()

print("=" * 72)
print("A. billing mentions")
print("=" * 72)
for kw in ("credit", "free", "billing", "cost", "showcaseFree", "Ou(", "guard",
           "permanent"):
    n = len(re.findall(re.escape(kw), js, re.I))
    print(f"   {kw!r:16} {n}")
print()

print("=" * 72)
print("B. the submit call and its payload")
print("=" * 72)
for m in re.finditer(r"submit", js, re.I):
    i = m.start()
    seg = js[max(0, i - 400):i + 400]
    if "hall-of-fame/submit" in seg or "mutationFn" in seg or "paipu" in seg:
        print("  *", seg.replace("\n", " ")[:700])
        print()
print()

print("=" * 72)
print("C. model selection / engine keys")
print("=" * 72)
for kw in ("model4p", "model3p", "engineKeys", "rigel", "model"):
    for m in list(re.finditer(re.escape(kw), js))[:2]:
        i = m.start()
        print(f"  [{kw}]", js[max(0, i - 260):i + 300].replace("\n", " ")[:560])
        print()
print()

print("=" * 72)
print("D. daily limit handling")
print("=" * 72)
for kw in ("DAILY", "daily", "remaining", "limit", "quota"):
    for m in list(re.finditer(kw, js))[:2]:
        i = m.start()
        print(f"  [{kw}]", js[max(0, i - 300):i + 320].replace("\n", " ")[:620])
        print()
