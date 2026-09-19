"""How many training entries does ONE log file produce?

If the loader emits all 4 players' POVs from a single file, then one file = 4
players' worth of decisions, and the filename's `tw` is just which seat the log
was downloaded for.  If it emits only one, each file covers a single POV.

This decides how many bigcoach reviews we need in order to cover the whole
training distribution with pi values.
"""
import glob
import sys

sys.path.insert(0, ".")
from libriichi.dataset import GameplayLoader

files = sorted(glob.glob("date/*.json.gz"))[:3]
loader = GameplayLoader(version=4, player_names=[], excludes=[], augmented=False)

for f in files:
    data = loader.load_gz_log_files([f])
    print(f"file: {f.split('/')[-1].split(chr(92))[-1]}")
    print(f"  outer list len : {len(data)}")
    for gi, group in enumerate(data):
        print(f"  group {gi}: {len(group)} gameplay(s)")
        for g in group:
            pid = g.take_player_id()
            obs = g.take_obs()
            print(f"     player_id={pid}  entries={len(obs)}")
    print()
