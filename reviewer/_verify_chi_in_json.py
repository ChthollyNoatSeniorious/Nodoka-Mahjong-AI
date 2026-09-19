"""Do chi actions in the review JSON carry the CALLED tile?

If details[].action for a chi includes both `consumed` and `pai`, then
low/mid/high can be computed exactly from the JSON alone -- no log lookup, no
ambiguity, no dropped samples.  That would remove the last weak point in the
distillation pipeline.
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

p = pathlib.Path(r"reviewer\out\_cached_test03.htm")
obj = json.loads(p.read_text(encoding="utf-8"))
entries = [e for k in obj["review"]["kyokus"] for e in k["entries"]]

print("=== all action keys seen in details ===")
keys = Counter()
for e in entries:
    for d in e["details"]:
        keys[tuple(sorted(d["action"].keys()))] += 1
for k, v in keys.most_common():
    print(f"  {v:5}  {k}")
print()

print("=== every call-type action (chi/pon/kan) in full ===")
shown = 0
for e in entries:
    for d in e["details"]:
        a = d["action"]
        if a.get("type") in ("chi", "pon", "kan", "daiminkan", "ankan", "kakan"):
            print(f"  {json.dumps(a, ensure_ascii=False)}")
            shown += 1
            if shown >= 12:
                break
    if shown >= 12:
        break
print()

# can we compute chi type from pai + consumed?
def tile_index(t):
    t = t.replace("r", "")
    HON = ["E", "S", "W", "N", "P", "F", "C"]
    if len(t) == 2 and t[0].isdigit():
        return {"m": 0, "p": 9, "s": 18}[t[1]] + int(t[0]) - 1
    return 27 + HON.index(t)

print("=== chi type computed from pai vs consumed (libriichi rule) ===")
n_chi = 0
for e in entries:
    for d in e["details"]:
        a = d["action"]
        if a.get("type") != "chi":
            continue
        cons = a.get("consumed") or []
        pai = a.get("pai")
        if len(cons) != 2 or not pai:
            print(f"  !! incomplete chi: {a}")
            continue
        lo, hi = sorted(tile_index(x) for x in cons)
        ti = tile_index(pai)
        idx = 38 if ti < lo else (39 if ti < hi else 40)
        n_chi += 1
        if n_chi <= 10:
            print(f"  consumed={cons} pai={pai} -> index {idx}")
print()
print(f"chi actions with complete pai+consumed: {n_chi}")
print("=> chi low/mid/high is exactly computable from the JSON alone."
      if n_chi else "=> chi still needs the log")
