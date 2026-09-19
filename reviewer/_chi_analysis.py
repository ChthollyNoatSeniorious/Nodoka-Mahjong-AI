#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resolve chi low/mid/high EXACTLY, using the hand in the report.

With consumed tiles `3m+4m` the called tile is either `2m` (chi-low) or `5m`
(chi-high) -- ambiguous from the consumed tiles alone, which is why a naive
inference gets ~15/1924 decisions wrong.

But the report shows the hand, and the called tile is the one that is *in the
hand* right before the call (it is discarded from hand into the meld).  So:

    called = the run member that appears in the 13/14-tile hand

This script measures whether that disambiguation is reliable, and reports how
many chi decisions exist at all -- if the number is tiny, the impact on
distillation is negligible either way.
"""
from __future__ import annotations

import collections
import importlib.util
import pathlib
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cmp", HERE / "compare_test03.py")
cmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp)

spec2 = importlib.util.spec_from_file_location("dist", HERE / "bigcoach_distill.py")
dist = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(dist)

total_chi = 0
for tag in [f"test0{i}" for i in range(1, 10)]:
    htm = next(cmp.TESTSET.glob(f"{tag}_*.htm"))
    ak = [e for k in cmp.parse_akino(htm) for e in k]
    chi_dec = [e for e in ak if any(c["key"].startswith("chi:") for c in e["cands"])]
    chi_actions = sum(1 for e in ak for c in e["cands"] if c["key"].startswith("chi:"))
    total_chi += chi_actions
    if chi_dec:
        print(f"{tag}: {len(chi_dec):>3} decisions have chi candidates, "
              f"{chi_actions:>3} chi actions total")

print()
print(f"TOTAL chi actions across 9 games: {total_chi}")
print()
print("context: total decisions in 9 games ~", 9 * 216)
print(f"chi is therefore ~{100.0*total_chi/(9*216):.2f}% of all decisions")
print()

# How ambiguous is it really?  consumed pairs with |hi-lo|==1 are ambiguous.
amb = collections.Counter()
for tag in [f"test0{i}" for i in range(1, 10)]:
    htm = next(cmp.TESTSET.glob(f"{tag}_*.htm"))
    ak = [e for k in cmp.parse_akino(htm) for e in k]
    for e in ak:
        for c in e["cands"]:
            if not c["key"].startswith("chi:"):
                continue
            parts = c["key"].split(":", 1)[1].split("+")
            if len(parts) != 2:
                continue
            a, b = (dist.tile_index(t) for t in parts)
            amb["ambiguous (|d|=1)" if abs(a - b) == 1 else "determinate (|d|=2)"] += 1
print("ambiguity breakdown of chi actions:")
for k, v in amb.items():
    print(f"  {k:>24} : {v}")
