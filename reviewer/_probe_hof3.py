#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify we can enumerate FREE RIGEL 1.4 analyses from the hall of fame.

    GET /hall-of-fame/players?page=N&pageSize=M         -> list of players
    GET /hall-of-fame/players/tenhou/{name}?page=N      -> that player's games
        each item has cachedRuns[] with {taskId, engineKeys, ...}

Filtering engineKeys == "rigel_14" gives 長明 1.4 (RIGEL 1.4) analyses only,
avoiding NOVA / zenith / halo / comet.  Downloading a cached run is free.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
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


def get(path, params=None):
    url = BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json", "Cookie": COOKIE,
        "Referer": "https://review.bigcoach.work/hall-of-fame"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


# ---- 1. one player's 4p games, showing cachedRuns -------------------------
NAME = "☆孫燕姿☆"
st, txt = get(f"/hall-of-fame/players/tenhou/{urllib.parse.quote(NAME)}",
              {"page": 1, "pageSize": 60})
d = json.loads(txt)["data"]
print(f"player {NAME}: total={d.get('total')} page={d.get('page')} "
      f"pageSize={d.get('pageSize')} items={len(d.get('items') or [])}")
print()

n4 = n3 = 0
rigel4 = rigel3 = 0
print("=== items with their cachedRuns (4p only) ===")
for it in d["items"]:
    if it.get("nplayer") != 4:
        n3 += 1
        continue
    n4 += 1
    runs = it.get("cachedRuns") or []
    engines = [r.get("engineKeys") for r in runs]
    if any(e == "rigel_14" for e in engines):
        rigel4 += 1
    if n4 <= 8:
        print(f"  paipu={it.get('canonicalId')} seat={it.get('seat')} "
              f"runs={len(runs)} engines={engines}")
print()
print(f"4p items: {n4}   3p items: {n3}")
print(f"4p items with a rigel_14 run: {rigel4}")
print()

# show the full cachedRun shape
for it in d["items"]:
    for r in (it.get("cachedRuns") or []):
        if r.get("engineKeys") == "rigel_14":
            print("=== full rigel_14 cachedRun ===")
            print(json.dumps(r, ensure_ascii=False, indent=1))
            print(f"  paipu = {it.get('canonicalId')}")
            print(f"  seat  = {it.get('seat')}")
            break
    else:
        continue
    break

# ---- 2. the player list ---------------------------------------------------
print()
st, txt = get("/hall-of-fame/players", {"page": 1, "pageSize": 24})
try:
    obj = json.loads(txt)
    dd = obj.get("data") or obj
    print(f"=== GET /hall-of-fame/players -> {st} ===")
    print(f"  keys: {list(dd.keys()) if isinstance(dd, dict) else type(dd)}")
    if isinstance(dd, dict):
        print(f"  total={dd.get('total')} page={dd.get('page')} "
              f"pageSize={dd.get('pageSize')} items={len(dd.get('items') or [])}")
        for it in (dd.get("items") or [])[:5]:
            keys = sorted(it.keys()) if isinstance(it, dict) else it
            print(f"    {json.dumps(it, ensure_ascii=False)[:260]}")
except Exception as exc:
    print("player list parse failed:", exc, txt[:300])
