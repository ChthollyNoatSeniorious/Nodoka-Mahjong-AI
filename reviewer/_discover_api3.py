#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pin down the exact HOF submit payload and the classic-report URL."""
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


def show(txt: str, needle: str, before: int = 260, after: int = 260,
         limit: int = 4, label: str = ""):
    print(f"----- {label or needle} -----")
    n = 0
    for m in re.finditer(re.escape(needle), txt):
        s = max(0, m.start() - before)
        e = min(len(txt), m.end() + after)
        print("  ..." + txt[s:e].replace("\n", " ") + "...")
        print()
        n += 1
        if n >= limit:
            break
    if not n:
        print("  (not found)")
    print()


for f in sorted(CACHE.glob("*.js")):
    txt = f.read_text(encoding="utf-8", errors="replace")
    if "hall-of-fame" not in txt and "classic" not in txt:
        continue
    print(f"########## {f.name} ##########")
    print()
    show(txt, "classic", label="classic URL construction")
    show(txt, "/hall-of-fame/submit", label="HOF submit call")
    show(txt, "/hall-of-fame/resolve", label="HOF resolve call")
    show(txt, "o_=", before=0, after=200, label="token helper o_")
    show(txt, "btoa", before=120, after=180, label="btoa usages (token encoding)")
