#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What does a review cost, and are there limits?

The hall-of-fame route returned "none" for the AI's games (the bot accounts are
not registered experts), so harvesting them needs the regular route:

    POST /api/v2/review   FormData: paipuId, playerId, m=<model>

The bundle mentions credits (`review_standard_4p`, `creditsOverride`) and the
error code HOF_DAILY_RUNS_EXCEEDED, so before harvesting 1765 games we need to
know the cost.  Find the account/credits endpoint in the bundle.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

CACHE = pathlib.Path(r"reviewer\out\_bundles")

PATTERNS = ["membership", "credits", "quota", "balance", "/me", "profile",
            "dailyRuns", "runsToday", "remaining"]

for f in sorted(CACHE.glob("*.js")):
    txt = f.read_text(encoding="utf-8", errors="replace")
    hits = {}
    for p in PATTERNS:
        for m in re.finditer(re.escape(p), txt, re.I):
            s = max(0, m.start() - 120)
            e = min(len(txt), m.end() + 120)
            sn = txt[s:e].replace("\n", " ")
            if "R.get" in sn or "R.post" in sn or "/api" in sn or "queryFn" in sn:
                hits.setdefault(p, []).append(sn)
    if hits:
        print(f"===== {f.name} =====")
        for p, sns in hits.items():
            seen = set()
            for sn in sns:
                key = sn[:60]
                if key in seen:
                    continue
                seen.add(key)
                print(f"  [{p}] ...{sn}...")
        print()
