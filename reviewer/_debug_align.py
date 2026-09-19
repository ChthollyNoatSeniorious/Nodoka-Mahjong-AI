"""Find why the replay has 6 more entries than the report, and how to align.

Hypothesis: when a kan happens, libriichi emits TWO entries -- the kan action
and a "which tile to kan" selection -- while the report shows one decision.
At the end of a game there may also be extra entries.

We look for a signature we can filter on from Python, since `at_kan_select` is
not exposed.  Candidates: mask population (a kan-select mask allows only the
kan-able tiles), and the observation content.
"""
from __future__ import annotations

import gzip
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
games = [g for grp in data for g in grp]
mine = next(g for g in games if g.take_player_id() == 0)

obs = mine.take_obs()
actions = mine.take_actions()
masks = mine.take_masks()
atk = mine.take_at_kyoku()
gamma = mine.take_apply_gamma()
turns = mine.take_at_turns()

htm = next(cmp.TESTSET.glob("test03_*.htm"))
report = [e for k in cmp.parse_akino(htm) for e in k]

print(f"replay entries: {len(actions)}   report decisions: {len(report)}")
print()
print("=== replay entry profile (looking for kan-select signature) ===")
print("%-5s %-6s %-6s %-6s %-7s %-8s %s" % (
    "#", "label", "mask#", "kyoku", "gamma", "turn", "mask tiles"))
for i in range(len(actions)):
    m = masks[i]
    nset = int(m.sum())
    tiles = [j for j in range(46) if bool(m[j])]
    # print only entries that look unusual (few legal actions)
    if nset <= 4:
        print("%-5d %-6d %-6d %-6d %-7s %-8d %s" % (
            i + 1, int(actions[i]), nset, int(atk[i]), bool(gamma[i]),
            int(turns[i]), tiles))
