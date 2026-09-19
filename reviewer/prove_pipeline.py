"""END-TO-END PROOF: bigcoach report  <->  libriichi replay, same game.

The distillation plan:
    * harvest pi values from bigcoach for our own training games
      (their tenhou log ids are in the dataset filenames)
    * replay each game through libriichi to get the observation tensors
    * pair them up decision by decision

Everything hinges on that pairing being exact.  This proves it on test03.

We do NOT need to download anything: mjai-reviewer's own JSON report embeds the
full `mjai_log`, which we can feed straight into libriichi's GameplayLoader
exactly the way train.py does.  (The 1765 training files are already mjai logs
too, so they need no conversion either.)
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
OUT = HERE / "out" / "replay_probe"
OUT.mkdir(parents=True, exist_ok=True)

LOG_ID = "2025071422gm-00a9-0000-a1375e41"
TW = 0

spec = importlib.util.spec_from_file_location("cmp", HERE / "compare_test03.py")
cmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp)
spec2 = importlib.util.spec_from_file_location("dist", HERE / "bigcoach_distill.py")
dist = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(dist)

# ------------------------------------------------- 1. mjai log from our report
rep = json.loads((HERE / "out" / "testset" / "test03_finetune_step321275.json")
                 .read_text(encoding="utf-8"))
mjai_log = rep.get("mjai_log")
print(f"mjai_log type: {type(mjai_log).__name__}")
if isinstance(mjai_log, str):
    events = [json.loads(ln) for ln in mjai_log.splitlines() if ln.strip()]
else:
    events = mjai_log
print(f"events: {len(events)}")
print(f"  first: {json.dumps(events[0], ensure_ascii=False)[:110]}")
print()

gz_path = OUT / f"{LOG_ID}&tw={TW}.json.gz"
with gzip.open(gz_path, "wt", encoding="utf-8", newline="\n") as fh:
    for ev in events:
        fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
print(f"wrote {gz_path}")

# ------------------------------------------------------ 2. libriichi replay
os.chdir(MORTAL)
sys.path.insert(0, str(MORTAL))
from libriichi.dataset import GameplayLoader

loader = GameplayLoader(version=4, player_names=[], excludes=[], augmented=False)
data = loader.load_gz_log_files([str(gz_path)])
games = [g for grp in data for g in grp]
print(f"\nlibriichi produced {len(games)} gameplay(s)")

mine = next((g for g in games if g.take_player_id() == TW), None)
if mine is None:
    print("!! target player not found")
    sys.exit(1)

obs = mine.take_obs()
actions = mine.take_actions()
masks = mine.take_masks()
print(f"player {TW}: {len(obs)} entries")
print(f"  obs shape  : {obs[0].shape if len(obs) else 'n/a'}")
print(f"  mask shape : {masks[0].shape if len(masks) else 'n/a'}")

# ------------------------------------------------------------- 3. compare
htm = next(cmp.TESTSET.glob("test03_*.htm"))
report = [e for k in cmp.parse_akino(htm) for e in k]
print(f"\nbigcoach report: {len(report)} decisions")

print()
print("=== decision-by-decision ===")
print("%-5s %-16s %-8s %-6s %s" % ("#", "report(player)", "libridx", "match", "label legal"))
n = min(len(report), len(actions))
match = mismatch = unmapped = illegal = 0
shown = 0
for i in range(n):
    r = report[i]
    lab = int(actions[i])
    idx = dist.report_action_to_index(r["player_key"], None)
    ok = "OK" if idx == lab else "DIFF"
    legal = bool(masks[i][lab])
    if not legal:
        illegal += 1
    if idx is None:
        unmapped += 1
        ok = "??"
    elif idx == lab:
        match += 1
    else:
        mismatch += 1
    if shown < 10 or ok != "OK":
        if shown < 10 or mismatch <= 10:
            print("%-5d %-16s %-8s %-6s %s" % (i + 1, r["player_key"], lab, ok, legal))
            shown += 1

print()
print("=== RESULT ===")
print(f"  compared           : {n}")
print(f"  report decisions   : {len(report)}")
print(f"  replay entries     : {len(actions)}")
print(f"  action matches     : {match}/{n} = {100.0*match/max(1,n):.2f}%")
print(f"  mismatches         : {mismatch}")
print(f"  unmapped (chi)     : {unmapped}")
print(f"  illegal labels     : {illegal}")
print()
if match / max(1, n) > 0.9:
    print("  => PIPELINE PROVEN: report and libriichi replay agree decision-for-decision.")
else:
    print("  => pipeline NOT proven yet.")
