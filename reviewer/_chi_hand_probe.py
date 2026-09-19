"""What does the report's hand look like at a chi decision?

We assumed the called tile is present in the hand, but the hand render may be
post-call (called tile moved into the meld).  Let's look at real examples and
compare against Mortal's own state for the same decision.
"""
from __future__ import annotations

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

# raw json too, for the full state
raw = json.loads((JSON_DIR / "test03_finetune_step321275.json").read_text(encoding="utf-8"))
raw_ent = [e for k in raw["review"]["kyokus"] for e in k["entries"]]

htm = next(cmp.TESTSET.glob("test03_*.htm"))
ak = [e for k in cmp.parse_akino(htm) for e in k]

shown = 0
for i, (a, r) in enumerate(zip(ak, raw_ent)):
    if not a["player_key"].startswith("chi:"):
        continue
    tehai = r["state"].get("tehai") or []
    print(f"--- decision {i+1} ---")
    print(f"  report player action : {a['player_key']}")
    print(f"  mortal actual        : {r['actual']}")
    print(f"  mortal state.tehai   : {' '.join(tehai)}")
    print(f"  mortal state key list: {list(r['state'].keys())}")
    fuuros = r["state"].get("fuuros")
    print(f"  mortal fuuros        : {fuuros}")
    cons = r["actual"].get("consumed")
    print(f"  mortal actual.consumed: {cons}   pai={r['actual'].get('pai')}")
    shown += 1
    if shown >= 6:
        break
