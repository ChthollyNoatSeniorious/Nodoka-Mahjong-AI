"""Is our model actually learning Akino Hana's POLICY, or just agreeing more?

The previous metric had a flaw: it credited decisions where the human had no
legal choice.  This script tests three sharper questions.

Q1. Held-out TRAINING-DOMAIN fit.
    Akino Hana self-play logs are the training data.  If the model learned the
    policy (not memorised the files), agreement must be high on *unseen* files
    from the same source.  We can measure this: exclude N files, measure on them.

Q2. Does agreement come from the policy or from position difficulty?
    Split decisions by how "forced" they are (Akino Hana's own pi on its top-1).
    If our model only matches when the decision is a no-brainer, it has learned
    little; if it matches on contested decisions too, it learned the policy.

Q3. Calibration.
    When our model is confident, is it right as often as Akino Hana is when it
    is that confident?  A policy-copying model should have a similar
    confidence/accuracy curve.
"""
import collections
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

sys.path.insert(0, str(HERE))
import importlib.util

spec = importlib.util.spec_from_file_location("cmp", HERE / "compare_test03.py")
cmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp)

TAGS = [f"test0{i}" for i in range(1, 10)]

ak_all = []
o_all = []
for tag in TAGS:
    ak = [e for k in cmp.parse_akino(next(cmp.TESTSET.glob(f"{tag}_*.htm"))) for e in k]
    ours, _ = cmp.load_ours(JSON_DIR / f"{tag}_finetune_step321275.json")
    o = [x for k in ours for x in k]
    if len(ak) != len(o):
        print(f"{tag}: length mismatch {len(ak)} vs {len(o)}")
        continue
    for a, x in zip(ak, o):
        # only decisions with a real choice, and only discards (both sides)
        if not a["player_key"].startswith("dahai:"):
            continue
        if not x["actual_key"].startswith("dahai:"):
            continue
        ak_all.append(a)
        o_all.append(x)

print("real discard decisions pooled over 9 games:", len(ak_all))
print()

# ---------------------------------------------------------------- Q2 / Q3
print("=== Q2: does agreement depend on how contested the decision is? ===")
print("(banded by Akino Hana's own pi on its top-1 choice)")
print()
bands = [(0, 40), (40, 60), (60, 80), (80, 101)]
hdr = "%-10s %7s %8s %9s %11s" % ("AK pi", "n", "we match", "match%", "AK agrees w/ human")
print(hdr)
print("-" * len(hdr))
for lo, hi in bands:
    sel = [(a, x) for a, x in zip(ak_all, o_all)
           if a["cands"] and lo <= a["cands"][0]["pi"] < hi]
    if not sel:
        continue
    n = len(sel)
    match = sum(1 for a, x in sel if cmp.cmp_key(a["coach_key"]) == cmp.cmp_key(x["key"]))
    ak_human = sum(1 for a, x in sel if a["rank"] == 1)
    lbl = f"{lo}-{hi if hi <= 100 else '100'}"
    print("%-10s %7d %8d %8.1f%% %10.1f%%" % (
        lbl, n, match, 100.0 * match / n, 100.0 * ak_human / n))

print()
tot = len(ak_all)
match_all = sum(1 for a, x in zip(ak_all, o_all)
                if cmp.cmp_key(a["coach_key"]) == cmp.cmp_key(x["key"]))
print("overall top-1 match with Akino Hana: %d/%d = %.2f%%" % (
    match_all, tot, 100.0 * match_all / tot))

# ---------------------------------------------------------------- Q3
print()
print("=== Q3: confidence calibration ===")
print("(our model's own prob on its top-1 vs whether it matched Akino Hana)")
print()
print("%-12s %7s %10s" % ("our prob", "n", "match AK"))
print("-" * 32)
for lo, hi in [(0, 40), (40, 60), (60, 80), (80, 101)]:
    sel = [(a, x) for a, x in zip(ak_all, o_all)
           if x.get("prob") is not None and lo <= x["prob"] * 100 < hi]
    if not sel:
        continue
    n = len(sel)
    match = sum(1 for a, x in sel if cmp.cmp_key(a["coach_key"]) == cmp.cmp_key(x["key"]))
    lbl = f"{lo}-{hi if hi <= 100 else '100'}"
    print("%-12s %7d %9.1f%%" % (lbl, n, 100.0 * match / n))
