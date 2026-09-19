"""Decisive check: does bigcoach's candidate list match the TRUE legal actions?

bigcoach's pi sums to exactly 100.000 over the candidates it lists.  Two possible
explanations:
  (a) it lists every legal action -> the pi is Akino Hana's raw policy, usable as-is
  (b) it filters out low-probability actions and renormalises -> the pi is biased
      upwards on the surviving actions, and distillation would learn "those
      actions do not exist"

We can settle this by comparing, decision by decision, against our OWN
mjai-reviewer report on the SAME game, which gets the legal action set straight
from Mortal's action mask (the ground truth).

Usage (repo root): python reviewer\\_check_candidates.py [testNN]
"""
import collections
import importlib.util
import json
import pathlib
import re
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

TAG = sys.argv[1] if len(sys.argv) > 1 else "test03"
htm = next(cmp.TESTSET.glob(f"{TAG}_*.htm"))
ak = [e for k in cmp.parse_akino(htm) for e in k]

ours, _ = cmp.load_ours(JSON_DIR / f"{TAG}_finetune_step321275.json")
o = [x for k in ours for x in k]

print(f"=== {TAG}: bigcoach candidates vs TRUE legal actions ===")
print()
print("comparing decision by decision...")
print()

rows = []
for i, (a, x) in enumerate(zip(ak, o)):
    ak_n = len(a["cands"])
    # our report carries the full candidate list for the state we asked about
    our_n = len(x["details"])
    rows.append((i, a, x, ak_n, our_n))

same = sum(1 for _, _, _, an, on in rows if an == on)
ak_less = sum(1 for _, _, _, an, on in rows if an < on)
ak_more = sum(1 for _, _, _, an, on in rows if an > on)
print(f"  identical candidate count : {same}/{len(rows)}")
print(f"  bigcoach lists FEWER      : {ak_less}/{len(rows)}")
print(f"  bigcoach lists MORE       : {ak_more}/{len(rows)}")
print()

print("=== examples where the counts differ ===")
print("%-5s %-9s %-9s %s" % ("dec", "bigcoach", "ours", "bigcoach's listed actions"))
shown = 0
for i, a, x, an, on in rows:
    if an != on and shown < 12:
        keys = ", ".join(c["key"] for c in a["cands"])
        print("%-5d %-9d %-9d %s" % (i + 1, an, on, keys[:90]))
        shown += 1
print()

# If bigcoach filtered, its smallest listed pi should be relatively large.
print("=== smallest listed pi per decision (filtering leaves a floor) ===")
mins = [min(c["pi"] for c in a["cands"]) for a in ak if a["cands"]]
print(f"  mean min pi : {sum(mins)/len(mins):.4f}")
print(f"  median      : {sorted(mins)[len(mins)//2]:.4f}")
print(f"  max min pi  : {max(mins):.4f}")
print()
cnt = collections.Counter()
for m in mins:
    if m < 0.05:
        cnt["< 0.05"] += 1
    elif m < 0.5:
        cnt["0.05-0.5"] += 1
    elif m < 1:
        cnt["0.5-1"] += 1
    else:
        cnt[">= 1"] += 1
print("  how small do listed probabilities get?")
for k in ["< 0.05", "0.05-0.5", "0.5-1", ">= 1"]:
    print(f"    {k:>9} : {cnt[k]}")
