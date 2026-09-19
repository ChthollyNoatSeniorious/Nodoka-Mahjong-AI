#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe the hall-of-fame import endpoints (read-only).

Found in the bundle:
    GET  /hall-of-fame/players/{platform}/{name}/importable
    POST /hall-of-fame/players/{platform}/{name}/import   {taskIds}
    POST /hall-of-fame/submit
    POST /hall-of-fame/resolve
    GET  /hall-of-fame/my-players

The submit path contains NO credit/billing/cost references -- its only limit is
a DAILY RUN COUNT (error code HOF_DAILY_RUNS_EXCEEDED).  That is consistent with
the user's idea being free, unlike POST /review which charges 10 credits.

This script only does GETs.  Nothing is submitted or imported.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

API = "https://review.bigcoach.work/api/v2"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def get(path, **params):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    r = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json",
        "Cookie": COOKIE, "Referer": "https://gokujan.com/hall-of-fame",
    })
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


if not COOKIE:
    print("set BIGCOACH_COOKIE first")
    sys.exit(2)

NAME = "☆孫燕姿☆"
print("=" * 72)
print(f"player: {NAME}")
print("=" * 72)

st, txt = get(f"/hall-of-fame/players/tenhou/{urllib.parse.quote(NAME)}",
              page=1, pageSize=60)
print(f"GET players/tenhou/<name>        -> HTTP {st} ({len(txt)} bytes)")
if st == 200:
    d = json.loads(txt)
    dd = d.get("data", d)
    items = dd.get("items") if isinstance(dd, dict) else dd
    print(f"    items: {len(items) if items else 0}")
    if items:
        it = items[0]
        print(f"    first item keys: {sorted(it.keys())}")
        cr = it.get("cachedRuns") or []
        print(f"    cachedRuns on first: {len(cr)}")
        if cr:
            print(f"      sample: {json.dumps(cr[0], ensure_ascii=False)[:300]}")
print()

st, txt = get(f"/hall-of-fame/players/tenhou/{urllib.parse.quote(NAME)}/importable")
print(f"GET .../importable               -> HTTP {st} ({len(txt)} bytes)")
if st == 200:
    print("    ", txt[:1200])
print()

st, txt = get("/hall-of-fame/my-players")
print(f"GET /hall-of-fame/my-players     -> HTTP {st} ({len(txt)} bytes)")
if st == 200:
    print("    ", txt[:800])
print()

print("=" * 72)
print("POST endpoints (NOT called -- listed for reference)")
print("=" * 72)
for p in ("/hall-of-fame/submit", "/hall-of-fame/resolve"):
    st, txt = get(p)
    print(f"    GET {p:28} -> {st}  (POST-only if 404/405)")
print()

print("=" * 72)
print("what features are enabled?")
print("=" * 72)
st, txt = get("/config")
if st == 200:
    cfg = json.loads(txt).get("data", json.loads(txt))
    feats = cfg.get("features") if isinstance(cfg, dict) else None
    print("    features:", json.dumps(feats, ensure_ascii=False)[:600]
          if feats else "(none)")
    for k in cfg if isinstance(cfg, dict) else []:
        if "hof" in k.lower() or "hall" in k.lower() or "run" in k.lower():
            print(f"    {k} = {json.dumps(cfg[k], ensure_ascii=False)[:300]}")
