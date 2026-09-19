#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inspect nodocchi's game list so we can build paipu URLs.

GET https://nodocchi.moe/api/listuser.php?name=<name>  -> ~2.5 MB JSON

We need the field that yields a Tenhou paipu link, because that is what the
hall-of-fame submit box accepts.  Read-only.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
NAME = "☆孫燕姿☆"

url = ("https://nodocchi.moe/api/listuser.php?name="
       + urllib.parse.quote(NAME))
r = urllib.request.Request(url, headers={
    "User-Agent": UA, "Referer": "https://nodocchi.moe/tenhoulog/",
    "Accept": "application/json", "Accept-Language": "ja,en;q=0.8"})
raw = urllib.request.urlopen(r, timeout=90).read().decode("utf-8", "replace")
print(f"bytes: {len(raw):,}")

obj = json.loads(raw)
print(f"top-level keys: {list(obj.keys())}")
lst = obj.get("list") or []
print(f"games: {len(lst):,}")
print()

if lst:
    e = lst[0]
    print("=== first entry, all fields ===")
    for k, v in e.items():
        print(f"   {k:16} = {v!r}")
    print()

    # look for anything that looks like a log id
    print("=== candidate id fields ===")
    for k in e:
        if any(t in k.lower() for t in ("log", "id", "game", "href", "url")):
            print(f"   {k} = {e[k]!r}")
    print()

    # distribution of 'sctype' (room) and 'playernum'
    from collections import Counter
    print("sctype   :", Counter(x.get("sctype") for x in lst).most_common())
    print("playernum:", Counter(x.get("playernum") for x in lst).most_common())
    print("playlength:", Counter(x.get("playlength") for x in lst).most_common())
    print()

    # how often is our player in which seat?
    print("=== seat occupancy for this player ===")
    cnt = Counter()
    for x in lst:
        for s in (1, 2, 3, 4):
            if x.get(f"player{s}") == NAME:
                cnt[s] += 1
    print("   ", dict(cnt))
    print()

    print("=== sample entries 2-4 ===")
    for x in lst[1:4]:
        print("   ", json.dumps(x, ensure_ascii=False)[:400])
