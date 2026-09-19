#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Full picture of a hall-of-fame player: 4p engines and the game list.

We want the endpoint that lists a player's games WITH their taskId + engineKey,
so we can bulk-download only rigel_14 (長明 1.4) analyses for free.
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
NAME = "☆孫燕姿☆"


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


st, txt = get(f"/hall-of-fame/players/tenhou/{urllib.parse.quote(NAME)}")
d = json.loads(txt)["data"]
print("=== player ===")
p = d["player"]
print(f"  name={p['playerKey']}  paipuCount={p['paipuCount']}  tags={p['tags']}")
print()
print("=== 4p engines that have analysed this player ===")
s4 = (p.get("stats") or {}).get("4p")
if s4:
    print(f"  games={s4.get('games')}  ranked={s4.get('rankedGames')}")
    for e in s4.get("byEngine", []):
        print(f"    {e['engineKey']:24} games={e['games']:<4} "
              f"matchRate={e.get('matchRate'):.4f} featured={e.get('featured')}")
else:
    print("  (no 4p stats)")
print()

print("=== other top-level keys in data ===")
for k, v in d.items():
    if k == "player":
        continue
    if isinstance(v, list):
        print(f"  {k}: list[{len(v)}]")
        if v and isinstance(v[0], dict):
            print(f"      item keys: {sorted(v[0].keys())}")
            print(f"      sample   : {json.dumps(v[0], ensure_ascii=False)[:400]}")
    elif isinstance(v, dict):
        print(f"  {k}: dict{list(v.keys())[:12]}")
    else:
        print(f"  {k}: {v}")
print()

# try to find a games/paipu listing
for cand in ("/hall-of-fame/players/{}/{}".format("tenhou", urllib.parse.quote(NAME)) + "/games",
             "/hall-of-fame/players/{}/{}/paipus".format("tenhou", urllib.parse.quote(NAME)),
             "/hall-of-fame/players/{}/{}/importable".format("tenhou", urllib.parse.quote(NAME))):
    st, txt = get(cand)
    print(f"GET {cand.split('/api/v2')[-1]} -> {st}  {txt[:260]}")
