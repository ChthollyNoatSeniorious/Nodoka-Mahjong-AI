"""Does the report's chi action text contain the CALLED tile?

Mortal records:  consumed = tiles from hand, pai = tile called from discarder.
At test03 decision 47: consumed 3m+4m, pai 5m.
The report renders the chi as 'chi:3m+4m' (only consumed).  But the report's
tehai-state may show the called tile separately, or the run may be inferable
from the hand: the called tile is NOT in hand, the consumed ones ARE.

So: called = the run member that is ABSENT from the hand (when unambiguous).
For consumed x,x+1 there are two runs; the absent-from-hand member identifies it.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import pathlib
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
JSON_DIR = HERE / "out" / "testset"
spec = importlib.util.spec_from_file_location("cmp", HERE / "compare_test03.py")
cmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp)
spec2 = importlib.util.spec_from_file_location("dist", HERE / "bigcoach_distill.py")
dist = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(dist)


def chi_index_from_hand(consumed, hand):
    """consumed: list of 2 mjai tiles. hand: list of tiles (pre-call).
    Returns (low/mid/high index, called_tile) or (None, None)."""
    a, b = (dist.tile_index(t) for t in consumed)
    lo, hi = min(a, b), max(a, b)
    hand_cnt = collections.Counter(dist.tile_index(t) for t in hand)
    # consume the two hand tiles
    hand_cnt[lo] -= 1
    hand_cnt[hi] -= 1

    cands = []
    if hi - lo == 1:
        cands = [t for t in (lo - 1, hi + 1) if t // 9 == lo // 9 and 0 <= t % 9 < 9]
    elif hi - lo == 2:
        cands = [lo + 1]
    else:
        return None, None
    # the called tile is the run member NOT in the (post-consumption) hand
    absent = [c for c in cands if hand_cnt.get(c, 0) <= 0]
    if len(absent) == 1:
        called = absent[0]
        return (38 if called < lo else (39 if called < hi else 40)), called
    if len(cands) == 1:
        called = cands[0]
        return (38 if called < lo else (39 if called < hi else 40)), called
    return None, None


raw = json.loads((JSON_DIR / "test03_finetune_step321275.json").read_text(encoding="utf-8"))
raw_ent = [e for k in raw["review"]["kyokus"] for e in k["entries"]]
htm = next(cmp.TESTSET.glob("test03_*.htm"))
ak = [e for k in cmp.parse_akino(htm) for e in k]

ok = bad = skip = 0
for i, (a, r) in enumerate(zip(ak, raw_ent)):
    act = r["actual"]
    if act.get("type") != "chi":
        continue
    hand = r["state"].get("tehai") or []
    idx, called = chi_index_from_hand(act["consumed"], hand)
    # ground truth from Mortal's own label
    nums = sorted([dist.tile_index(x) for x in act["consumed"]] + [dist.tile_index(act["pai"])])
    called_gt = dist.tile_index(act["pai"])
    lo_gt, hi_gt = min(dist.tile_index(x) for x in act["consumed"]), max(dist.tile_index(x) for x in act["consumed"])
    gt = 38 if called_gt < lo_gt else (39 if called_gt < hi_gt else 40)
    if idx is None:
        skip += 1
        print(f"dec {i+1}: UNRESOLVED consumed={act['consumed']} hand={' '.join(hand)} gt={gt}")
    elif idx == gt:
        ok += 1
    else:
        bad += 1
        print(f"dec {i+1}: WRONG consumed={act['consumed']} called_gt={act['pai']} "
              f"hand={' '.join(hand)} got={idx} want={gt}")

print()
print(f"chi decisions: ok={ok} bad={bad} unresolved={skip}")
