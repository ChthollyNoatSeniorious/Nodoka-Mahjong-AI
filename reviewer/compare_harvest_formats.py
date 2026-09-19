#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Do the free-harvest reviews match the format export_distill.py expects?

Old (paid/cached) harvest -> reviewer/out/hof/*.json
New (free submit)         -> reviewer/out/hof_free/*.json

If the shapes agree, the existing export path works unchanged and the new games
can be appended to the distillation set directly.
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


def summarize(p: pathlib.Path):
    try:
        rev = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return f"  {p.name}: unreadable ({e})"
    rv = rev.get("review", {})
    kyo = rv.get("kyokus") or []
    ents = sum(len(k.get("entries") or []) for k in kyo)
    e0 = (kyo[0].get("entries") or [{}])[0] if kyo else {}
    det = e0.get("details") or []
    return (f"  {p.name[:44]:44} top={sorted(rev.keys())}\n"
            f"      review keys: {sorted(rv.keys())[:10]}\n"
            f"      modelName={rv.get('modelName')!r} temp={rv.get('temperature')!r}\n"
            f"      kyokus={len(kyo)} entries={ents} mjai_log={'mjai_log' in rev}\n"
            f"      entry keys: {sorted(e0.keys())}\n"
            f"      first detail: {json.dumps(det[0], ensure_ascii=False)[:150] if det else '(none)'}")


old = sorted(pathlib.Path("reviewer/out/hof").glob("*.json"))
new = sorted(pathlib.Path("reviewer/out/hof_free").glob("*.json"))
print(f"old harvest (hof)      : {len(old)} files")
print(f"new harvest (hof_free) : {len(new)} files")
print()
print("=== OLD (one sample) ===")
if old:
    print(summarize(old[0]))
print()
print("=== NEW (all) ===")
for p in new:
    print(summarize(p))
    print()
