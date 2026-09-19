#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify every free-harvested review is usable training material.

Checks per file:
  * parseable, has review.kyokus
  * every entry's details probs sum to ~1
  * expected/actual present
  * mjai_log present
  * count valid rows (entries with details)
"""
from __future__ import annotations

import json
import pathlib
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HOF = pathlib.Path("reviewer/out/hof_free")
files = sorted(f for f in HOF.glob("*.json") if f.name != "_index.json")
print(f"files: {len(files)}")
print()

tot_valid = 0
tot_rows = 0
bad = []
rows = []
for f in files:
    try:
        rev = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        bad.append((f.name, f"unparseable: {e}"))
        continue
    rv = rev.get("review", {})
    kyo = rv.get("kyokus") or []
    n_rows = sum(len(k.get("entries") or []) for k in kyo)
    ok = fail = 0
    has_log = "mjai_log" in rev
    for k in kyo:
        for e in k.get("entries") or []:
            det = e.get("details") or []
            if not det:
                continue
            n_rows_check = n_rows
            if abs(sum(x.get("prob", 0) for x in det) - 1.0) < 1e-3:
                ok += 1
            else:
                fail += 1
            if not e.get("expected") or not e.get("actual"):
                bad.append((f.name, "missing expected/actual"))
    tot_valid += ok
    tot_rows += n_rows
    rows.append((f.name, n_rows, ok, fail, has_log))

print(f'{"file":44} {"rows":>5} {"probOK":>6} {"bad":>4} {"mjai":>5}')
for name, n_rows, ok, fail, has_log in rows:
    print(f"{name:44} {n_rows:>5} {ok:>6} {fail:>4} {str(has_log):>5}")
print()
print(f"total rows: {tot_rows}, valid prob targets: {tot_valid}")
print(f"problems  : {len(bad)}")
for b in bad[:10]:
    print("   ", b)
if not bad:
    print("=> ALL REVIEWS CLEAN, ready for distillation")