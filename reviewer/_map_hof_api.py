#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Map the hall-of-fame API surface.

Goal: enumerate already-analysed games so we can download RIGEL 1.4 (rigel_14)
reviews for free, without spending credits.

Seen so far:
    POST /hall-of-fame/resolve {paipu} -> cachedRuns[].taskId, engineKeys
    GET  /hall-of-fame/my-players
    GET  /hall-of-fame/players/{platform}/{name}/importable
    POST /hall-of-fame/players/{platform}/{name}/import {taskIds}
We need the endpoint that LISTS players and the endpoint that lists a player's
games/runs.
"""
from __future__ import annotations

import pathlib
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

CACHE = pathlib.Path(r"reviewer\out\_bundles")

for f in sorted(CACHE.glob("*.js")):
    txt = f.read_text(encoding="utf-8", errors="replace")
    if "hall-of-fame" not in txt:
        continue
    print(f"########## {f.name} ##########")
    print()
    # every R.get/R.post/patch/delete call that mentions hall-of-fame
    for m in re.finditer(r'R\.(get|post|patch|delete)\(\s*[`"\']([^`"\']*hall-of-fame[^`"\']*)',
                         txt):
        method = m.group(1).upper()
        path = m.group(2)
        print(f"  {method:6} {path}")
    print()
    # query keys
    print("  --- query keys mentioning hof ---")
    for m in re.finditer(r'queryKey:\s*\[([^\]]{0,160})\]', txt):
        if "hof" in m.group(1).lower() or "hall" in m.group(1).lower():
            print(f"    [{m.group(1)}]")
    print()
    # engineKeys / model keys
    print("  --- engineKeys references ---")
    seen = set()
    for m in re.finditer(r'engineKeys', txt):
        s = max(0, m.start() - 150)
        e = min(len(txt), m.end() + 150)
        sn = txt[s:e].replace("\n", " ")
        if sn[:60] in seen:
            continue
        seen.add(sn[:60])
        print(f"    ...{sn}...")
    print()
