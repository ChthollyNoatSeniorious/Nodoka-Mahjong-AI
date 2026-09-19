#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How much FREE RIGEL 1.4 (長明 1.4) data is in the hall of fame?

    GET /hall-of-fame/players                     -> list of players
    GET /hall-of-fame/players/{plat}/{name}?page= -> their games + cachedRuns

Counting gives us the real budget for the distillation set, at zero credit cost.
"""
from __future__ import annotations

import json
import os
import sys
import time
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
RIGEL = "rigel_14"


def get(path, params=None):
    url = BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json", "Cookie": COOKIE,
        "Referer": "https://review.bigcoach.work/hall-of-fame"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception:
            time.sleep(1 + attempt)
    return 0, ""


st, txt = get("/hall-of-fame/players")
obj = json.loads(txt)
players = obj.get("data") if isinstance(obj, dict) else obj
if not isinstance(players, list):
    print("unexpected shape:", txt[:300])
    sys.exit(1)

print(f"HOF players listed: {len(players)}")
print()
print("=== first 5 player entries ===")
for p in players[:5]:
    if isinstance(p, dict):
        print(f"  {json.dumps(p, ensure_ascii=False)[:300]}")
    else:
        print(f"  {p}")
print()

# sample the first N players and count rigel_14 4p runs
SAMPLE = 12
total_games = 0
total_rigel = 0
total_rigel_single = 0
rows = []
for p in players[:SAMPLE]:
    if not isinstance(p, dict):
        continue
    plat = p.get("platform", "tenhou")
    name = p.get("playerKey") or p.get("displayName")
    if not name:
        continue
    # pageSize is capped by the server (100 -> 422); 60 is accepted
    items = []
    page = 1
    while page <= 12:
        st, txt = get(f"/hall-of-fame/players/{plat}/{urllib.parse.quote(name)}",
                      {"page": page, "pageSize": 60})
        try:
            d = json.loads(txt).get("data")
        except Exception:
            d = None
        if not isinstance(d, dict):
            if page == 1:
                print(f"  !! {name}: HTTP {st} {txt[:110]}")
            break
        got = d.get("items") or []
        items += got
        if len(got) < 60 or len(items) >= (d.get("total") or 0):
            break
        page += 1
    items = items
    n4 = sum(1 for i in items if i.get("nplayer") == 4)
    exact = composite = 0
    for i in items:
        if i.get("nplayer") != 4:
            continue
        for r in (i.get("cachedRuns") or []):
            ek = (r.get("engineKeys") or "").strip()
            if ek == RIGEL:
                exact += 1
            elif RIGEL in [x.strip() for x in ek.split(",")]:
                composite += 1
    total_games += n4
    total_rigel_single += exact
    total_rigel += exact + composite
    rows.append((name, len(items), n4, exact, composite))
    time.sleep(0.3)

print(f"=== sampled {len(rows)} players ===")
print(f"{'player':<22} {'games':>6} {'4p':>5} {'rigel14':>8} {'composite':>10}")
for name, tot, n4, ex, co in rows:
    print(f"{name[:22]:<22} {tot:>6} {n4:>5} {ex:>8} {co:>10}")
print()
print(f"4p games sampled          : {total_games}")
print(f"exact 'rigel_14' runs     : {total_rigel_single}")
print(f"including compare runs    : {total_rigel}")
if rows:
    per = total_rigel_single / len(rows)
    print()
    print(f"rigel_14 4p runs per player: {per:.1f}")
    print(f"projected over {len(players)} players: ~{per*len(players):.0f} games")
    print(f"  -> ~{per*len(players)*216:,.0f} training decisions (at ~216/decision game)")
