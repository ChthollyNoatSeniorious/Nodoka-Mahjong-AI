"""Determine the exact alignment rule between a bigcoach report and a replay.

Findings so far:
  * replay has 222 entries, report has 216 -> 6 extra entries
  * entries with mask.sum()==1 look like kan-select entries (libriichi emits an
    extra entry for "which tile to kan" when always_include_kan_select is on)

Test two candidate rules and measure agreement:
  R1: drop replay entries with mask.sum()==1
  R2: difflib sequence alignment between report action indices and replay labels

R2 is the robust one; R1 is a hypothesis about the cause.
"""
from __future__ import annotations

import difflib
import importlib.util
import json
import os
import pathlib
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
MORTAL = ROOT / "mortal"

spec = importlib.util.spec_from_file_location("cmp", HERE / "compare_test03.py")
cmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp)
spec2 = importlib.util.spec_from_file_location("dist", HERE / "bigcoach_distill.py")
dist = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(dist)

gz = HERE / "out" / "replay_probe" / "2025071422gm-00a9-0000-a1375e41&tw=0.json.gz"
os.chdir(MORTAL)
sys.path.insert(0, str(MORTAL))
from libriichi.dataset import GameplayLoader

loader = GameplayLoader(version=4, player_names=[], excludes=[], augmented=False)
data = loader.load_gz_log_files([str(gz)])
mine = next(g for grp in data for g in grp if g.take_player_id() == 0)
actions = mine.take_actions()
masks = mine.take_masks()

htm = next(cmp.TESTSET.glob("test03_*.htm"))
report = [e for k in cmp.parse_akino(htm) for e in k]

rep_idx = [dist.report_action_to_index(r["player_key"]) for r in report]
rep_txt = [r["player_key"] for r in report]

print(f"report {len(report)}   replay {len(actions)}")
print()

# ---------------------------------------------------------------- R1
keep = [j for j in range(len(actions)) if int(masks[j].sum()) != 1]
print(f"=== R1: drop entries with mask.sum()==1 ===")
print(f"  dropped {len(actions)-len(keep)} entries -> {len(keep)} remain")
n = min(len(rep_idx), len(keep))
m = sum(1 for i in range(n)
        if rep_idx[i] is None or rep_idx[i] == int(actions[keep[i]]))
print(f"  agreement: {m}/{n} = {100.0*m/n:.2f}%")
print()

# ---------------------------------------------------------------- R2
print("=== R2: difflib sequence alignment ===")
# build comparable symbol lists; use '?' for unmapped (chi) so they can match anything
a_syms = [("?" if x is None else str(x)) for x in rep_idx]
b_syms = [str(int(x)) for x in actions]
sm = difflib.SequenceMatcher(a=a_syms, b=b_syms, autojunk=False)
pairs = []
for op, i1, i2, j1, j2 in sm.get_opcodes():
    if op == "equal":
        for k in range(i2 - i1):
            pairs.append((i1 + k, j1 + k))
    elif op in ("replace",):
        na, nb = i2 - i1, j2 - j1
        for k in range(min(na, nb)):
            pairs.append((i1 + k, j1 + k))
print(f"  matched pairs: {len(pairs)}")
missing_a = [i for i in range(len(rep_idx)) if i not in {p[0] for p in pairs}]
extra_b = [j for j in range(len(actions)) if j not in {p[1] for p in pairs}]
print(f"  report entries unmatched : {len(missing_a)}")
print(f"  replay entries unmatched : {len(extra_b)}")
print()
if extra_b:
    print("  extra replay entries (index, label, mask#, mask tiles):")
    for j in extra_b:
        tiles = [x for x in range(46) if bool(masks[j][x])]
        print(f"    {j+1:>4}  label={int(actions[j]):<4} mask#={int(masks[j].sum()):<3} {tiles}")
print()
ok = sum(1 for i, j in pairs
         if rep_idx[i] is None or rep_idx[i] == int(actions[j]))
tot = len(pairs)
print(f"  pairwise agreement: {ok}/{tot} = {100.0*ok/max(1,tot):.2f}%")
print()
if extra_b:
    print("  => the extra entries are the kan-select ones; R2 handles them.")
