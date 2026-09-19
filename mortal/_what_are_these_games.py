#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What are the 1765 training games, and will bigcoach review them?

`POST /hall-of-fame/resolve` said "none" for a training game but "listed" for
test03, so the hall-of-fame route may only cover games by registered experts.
The regular route is `POST /api/v2/review` (FormData: paipuId, playerId, m).

First understand the data: who plays in these games?
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
print(f"training files: {len(files)}")
print()

name_sets = collections.Counter()
per_seat = collections.defaultdict(collections.Counter)
samples = []

for f in files[:40]:
    with gzip.open(f, "rt", encoding="utf-8") as fh:
        first = json.loads(fh.readline())
    names = tuple(first.get("names") or [])
    name_sets[names] += 1
    tw = pathlib.Path(f).name.split("&tw=")[-1].split(".")[0]
    if len(names) == 4:
        per_seat[tw][names[int(tw)]] += 1
        samples.append((pathlib.Path(f).name[:24], tw, names))

print("=== distinct 4-name sets among the first 40 files ===")
for k, v in name_sets.most_common(8):
    print(f"  {v:3}x  {k}")
print()

print("=== who sits in the file's own `tw` seat? ===")
for tw in sorted(per_seat):
    print(f"  tw={tw}: {dict(per_seat[tw].most_common(5))}")
print()

print("=== sample files ===")
for name, tw, names in samples[:10]:
    print(f"  {name}  tw={tw}")
    print(f"      names = {list(names)}")
print()

# is any single name common across ALL files? (would indicate the bot)
all_names = collections.Counter()
for f in files[:200]:
    with gzip.open(f, "rt", encoding="utf-8") as fh:
        first = json.loads(fh.readline())
    tw = int(pathlib.Path(f).name.split("&tw=")[-1].split(".")[0])
    names = first.get("names") or []
    if len(names) == 4:
        all_names[names[tw]] += 1
print("=== most common name in the tw seat (first 200 files) ===")
for k, v in all_names.most_common(10):
    print(f"  {v:4}x  {k!r}")
