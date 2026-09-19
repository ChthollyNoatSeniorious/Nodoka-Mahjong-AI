#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How many reviews can the account afford, and what are the limits?

    GET /api/v2/membership/status   -> credits, membership
    GET /api/v2/config              -> membership.creditCosts, models, features

Read-only calls.
"""
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


st, txt = get("/membership/status")
print(f"===== GET /membership/status -> {st} =====")
try:
    obj = json.loads(txt)
    print(json.dumps(obj, ensure_ascii=False, indent=1)[:2500])
except Exception:
    print(txt[:1200])
print()

st, txt = get("/config")
print(f"===== GET /config -> {st} =====")
try:
    cfg = json.loads(txt)
    d = cfg.get("data") or cfg
    mem = d.get("membership") or {}
    print("membership keys:", list(mem.keys()))
    print()
    print("creditCosts:", json.dumps(mem.get("creditCosts"), ensure_ascii=False, indent=1)[:900])
    print()
    mods = d.get("models") or mem.get("models")
    if mods:
        print("models:", json.dumps(mods, ensure_ascii=False, indent=1)[:1200])
    print()
    for k in ("features", "review", "limits"):
        if k in d:
            print(f"{k}:", json.dumps(d[k], ensure_ascii=False)[:700])
except Exception as exc:
    print("parse failed:", exc)
    print(txt[:1500])
