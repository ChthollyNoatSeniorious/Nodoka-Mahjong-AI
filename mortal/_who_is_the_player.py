#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Definitive: WHO is the reviewed player (the `tw` seat) in the 1765 files?

The distillation target is "whatever the POV player did".  If that player is a
human, we would be distilling a human, not Akino Hana -- which would explain a
lot about the results so far.  So this needs to be settled with data.
"""
from __future__ import annotations

import collections
import glob
import gzip
import json
import pathlib
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

files = sorted(glob.glob("mortal/date/*.json.gz"))
seat_names = collections.Counter()
all_names = collections.Counter()
by_seat = collections.defaultdict(collections.Counter)
bad = 0

for f in files:
    try:
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            first = json.loads(fh.readline())
    except Exception:
        bad += 1
        continue
    names = first.get("names") or []
    tw = int(pathlib.Path(f).name.split("&tw=")[-1].split(".")[0])
    if len(names) != 4:
        continue
    seat_names[names[tw]] += 1
    by_seat[tw][names[tw]] += 1
    for n in names:
        all_names[n] += 1

print(f"files: {len(files)}  (unreadable: {bad})")
print()
print("=== POV player (the `tw` seat) across ALL files ===")
for k, v in seat_names.most_common(15):
    print(f"  {v:5}x  {100.0*v/sum(seat_names.values()):5.1f}%  {k!r}")
print()
print("=== POV player per seat ===")
for tw in sorted(by_seat):
    top = by_seat[tw].most_common(4)
    print(f"  tw={tw}: " + ", ".join(f"{n!r} x{c}" for n, c in top))
print()
print("=== most frequent names anywhere in the games ===")
for k, v in all_names.most_common(12):
    print(f"  {v:5}x  {k!r}")
print()
tot = sum(seat_names.values())
har = seat_names.get("ハラヤハ", 0)
aki = seat_names.get("秋野花", 0)
print(f"POV == ハラヤハ : {har}/{tot} = {100.0*har/tot:.1f}%")
print(f"POV == 秋野花   : {aki}/{tot} = {100.0*aki/tot:.1f}%")
print(f"POV == neither  : {tot-har-aki}/{tot} = {100.0*(tot-har-aki)/tot:.1f}%")
