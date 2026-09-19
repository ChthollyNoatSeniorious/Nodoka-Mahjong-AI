#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify harvested hall-of-fame reviews before building the distillation set.

Checks, per file:
  * the model really is RIGEL 1.4 (not NOVA / zenith / a compare run)
  * details[].prob sums to 1
  * argmax(details) == expected
  * mjai_log is present (needed to replay for obs tensors)
  * 4-player only
"""
from __future__ import annotations

import collections
import glob
import json
import pathlib
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

files = sorted(glob.glob("reviewer/out/hof/*.json"))
files = [f for f in files if not f.endswith("_index.json")]
print(f"harvested files: {len(files)}")
print()

models = collections.Counter()
tiers = collections.Counter()
nplayer = collections.Counter()
bad_sum = bad_argmax = no_log = 0
total_dec = 0
game_ids = set()

for f in files:
    obj = json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
    eng = obj.get("_engine") or {}
    models[eng.get("modelName")] += 1
    nplayer[obj.get("nplayer")] += 1
    hof = obj.get("_hof") or {}
    game_ids.add(hof.get("canonicalId"))
    log = obj.get("mjai_log")
    if not log:
        no_log += 1
    rev = obj.get("review") or {}
    entries = [e for k in (rev.get("kyokus") or []) for e in k.get("entries") or []]
    total_dec += len(entries)
    for e in entries:
        det = e.get("details") or []
        if not det:
            continue
        s = sum(d.get("prob", 0) for d in det)
        if abs(s - 1.0) > 1e-4:
            bad_sum += 1
        top = max(det, key=lambda d: d.get("prob", 0))["action"]
        if top != e.get("expected"):
            bad_argmax += 1

print("=== model names ===")
for k, v in models.most_common():
    print(f"  {v:4}x  {k}")
print()
print("=== player count ===")
for k, v in nplayer.most_common():
    print(f"  {v:4}x  nplayer={k}")
print()
print(f"distinct games        : {len(game_ids)}")
print(f"total decisions       : {total_dec:,}")
print(f"files without mjai_log: {no_log}")
print(f"prob sums != 1        : {bad_sum}")
print(f"argmax != expected    : {bad_argmax}")
print()
ok = (not no_log and not bad_sum and not bad_argmax
      and set(models) == {"RIGEL 1.4"} and set(nplayer) == {4})
print("=> ALL CHECKS PASSED, safe to distil." if ok
      else "=> problems found, inspect before distilling.")
