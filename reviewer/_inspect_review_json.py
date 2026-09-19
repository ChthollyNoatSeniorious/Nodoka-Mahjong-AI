#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inspect the structured review JSON behind a bigcoach task.

This is better than the classic HTML: it is authoritative, machine readable, and
comes with a signed token handed out by /tasks/{id}/result -- so no HTML
scraping and no token forging.
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

p = pathlib.Path(r"reviewer\out\_cached_test03.htm")
obj = json.loads(p.read_text(encoding="utf-8"))

print("top-level keys:")
for k, v in obj.items():
    t = type(v).__name__
    if isinstance(v, list):
        print(f"  {k:24} list[{len(v)}]")
    elif isinstance(v, dict):
        print(f"  {k:24} dict{list(v.keys())[:8]}")
    else:
        s = str(v)
        print(f"  {k:24} {t} = {s[:70]}")
print()

# find where the per-decision data lives
def find_decisions(o, path=""):
    """Look for a list whose items look like a decision (has candidates/actions)."""
    hits = []
    if isinstance(o, dict):
        for k, v in o.items():
            hits += find_decisions(v, f"{path}.{k}" if path else k)
    elif isinstance(o, list):
        if o and isinstance(o[0], dict):
            keys = set(o[0].keys())
            interesting = {"actions", "candidates", "pi", "q", "probs", "best",
                           "action", "expect", "actual"}
            if keys & interesting:
                hits.append((path, len(o), sorted(keys)[:14]))
        for i, v in enumerate(o[:2]):
            hits += find_decisions(v, f"{path}[{i}]")
    return hits


print("=== candidate decision containers ===")
for path, n, keys in find_decisions(obj)[:20]:
    print(f"  {path}  ({n} items)")
    print(f"      keys: {keys}")
print()

# dump a sample decision in full
for path, n, keys in find_decisions(obj):
    if n > 5:
        node = obj
        for part in path.replace("]", "").replace("[", ".").split("."):
            if not part:
                continue
            node = node[int(part)] if isinstance(node, list) else node[part]
        print(f"=== sample item from {path} ===")
        print(json.dumps(node[0], ensure_ascii=False, indent=1)[:2500])
        break
