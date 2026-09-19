"""How much probability mass is still dropped by unresolved chi candidates?

After resolving chi via the log's called tile, the remaining unmapped cases are
rows where the player did NOT chi (so there is no chi event in the log) but the
report lists chi alternatives.  Those alternatives should carry tiny pi.

If the dropped mass is small the dataset is safe; if not, we need the
discarder's tile for those rows too.
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

dropped_rows = 0
dropped_mass = 0.0
total_mass = 0.0
worst = []

for n in range(1, 11):
    tag = f"test{n:02d}"
    jf = JSON_DIR / f"{tag}_finetune_step321275.json"
    rep = json.loads(jf.read_text(encoding="utf-8"))
    log = rep.get("mjai_log")
    events = ([json.loads(x) for x in log.splitlines() if x.strip()]
              if isinstance(log, str) else log)
    pid = rep.get("player_id", 0)
    htm = next(cmp.TESTSET.glob(f"{tag}_*.htm"))
    rows = [e for k in cmp.parse_akino(htm) for e in k]

    chi_calls = [ev["pai"] for ev in events
                 if ev.get("type") == "chi" and ev.get("actor") == pid]
    ci = 0
    for r in rows:
        called = None
        if r["player_key"].startswith("chi:") and ci < len(chi_calls):
            called = chi_calls[ci]
            ci += 1
        for c in r["cands"]:
            total_mass += c["pi"]
            if dist.report_action_to_index(c["key"], None, called) is None:
                dropped_rows += 1
                dropped_mass += c["pi"]
                worst.append((c["pi"], c["key"], r["player_key"]))

print(f"total candidate pi mass : {total_mass:,.1f}")
print(f"dropped candidate count : {dropped_rows}")
print(f"dropped pi mass         : {dropped_mass:,.1f}"
      f"  ({100.0*dropped_mass/total_mass:.4f}% of all mass)")
print()
worst.sort(reverse=True)
print("largest dropped candidates:")
for pi, key, pk in worst[:10]:
    print(f"   pi={pi:7.3f}  {key:<16} (player actually: {pk})")
print()
if dropped_mass / total_mass < 0.001:
    print("=> negligible (<0.1%). Dataset is safe to train on.")
else:
    print("=> NOT negligible; resolve these too before training.")
