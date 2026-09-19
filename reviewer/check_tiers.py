#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Membership tiers and the zero-cost 'ai_analysis' option."""
from __future__ import annotations

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


def get(path):
    req = urllib.request.Request(BASE + path, headers={
        "User-Agent": UA, "Accept": "application/json", "Cookie": COOKIE,
        "Referer": "https://review.bigcoach.work/"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


st, txt = get("/config")
cfg = json.loads(txt)
d = cfg.get("data") or cfg
mem = d.get("membership") or {}

print("=== membership tiers ===")
print(json.dumps(mem.get("tiers"), ensure_ascii=False, indent=1)[:1500])
print()
print("=== limits / access ===")
for k in ("anonDailyReviewLimit", "dispatchAccess", "passChannelMultiplier"):
    print(f"  {k} = {mem.get(k)}")
print()

print("=== payment packages ===")
st, txt = get("/payment/packages")
try:
    p = json.loads(txt).get("data") or {}
    print(json.dumps(p, ensure_ascii=False, indent=1)[:1800])
except Exception:
    print(txt[:800])
