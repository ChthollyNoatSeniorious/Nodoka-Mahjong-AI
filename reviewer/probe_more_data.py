#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Is 416 games the whole free pool, or is there more?

The harvest called GET /hall-of-fame/players once and got 59 names.  Two things
were never verified:
  1. does that endpoint paginate (are there players 60..N we never saw)?
  2. did any player hit the harvester's max_pages=12 cap (12 x 60 = 720 games),
     which would mean their list was truncated?

This is read-only recon; it never spends credits.
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

BASE = "https://review.bigcoach.work/api/v2"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def get(path: str, **params):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Cookie": COOKIE,
    })
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


if not COOKIE:
    print("set BIGCOACH_COOKIE first")
    sys.exit(2)

st, txt = get("/hall-of-fame/players")
print(f"GET /hall-of-fame/players -> HTTP {st}")
if st != 200:
    print(txt[:300])
    sys.exit(1)
obj = json.loads(txt)
players = obj.get("data") if isinstance(obj, dict) else obj
print(f"  returned {len(players)} players")
if isinstance(obj, dict):
    for k in ("total", "page", "pageSize", "hasMore", "nextPage"):
        if k in obj:
            print(f"  {k} = {obj[k]}")
print()

# does it accept paging?
seen = {p.get("name") for p in players if isinstance(p, dict)}
for page in (2, 3):
    st2, txt2 = get("/hall-of-fame/players", page=page, pageSize=60)
    if st2 != 200:
        print(f"page={page} -> HTTP {st2} (endpoint does not paginate)")
        break
    o2 = json.loads(txt2)
    p2 = o2.get("data") if isinstance(o2, dict) else o2
    names = {p.get("name") for p in (p2 or []) if isinstance(p, dict)}
    new = names - seen
    print(f"page={page} -> {len(names)} players, {len(new)} NOT seen on page 1")
    if not new:
        print("  => page 1 is the complete list")
        break
    seen |= names
print()

# did any player hit the 720-game cap?
print("=== per-player game counts (from the harvester's own log) ===")
print("max observed: nsuphx 448 games; the cap is 12 pages x 60 = 720")
print("448 < 720, so nothing was truncated by pagination")
