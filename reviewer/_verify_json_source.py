"""Does the bigcoach review JSON give us everything we need?

If the JSON is the same format as mjai-reviewer's own output, then:
  * details[].prob IS the pi distribution (no HTML scraping needed)
  * mjai_log lets us replay through libriichi for the obs tensors
  * the alignment we already validated at 100% applies unchanged

Check: model tag, total_reviewed, prob normalisation, and whether the argmax of
details matches `expected` (and the 77.3% baseline in the filename).
"""
from __future__ import annotations

import json
import pathlib
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

p = pathlib.Path(r"reviewer\out\_cached_test03.htm")
obj = json.loads(p.read_text(encoding="utf-8"))
rev = obj["review"]

print("=== review metadata ===")
for k in ("total_reviewed", "total_matches", "rating", "temperature",
          "model_tag", "grade"):
    print(f"  {k:16} = {rev.get(k)}")
print(f"  player_id        = {obj.get('player_id')}")
print(f"  lang             = {obj.get('lang')}")
print(f"  mjai_log events  = {len(obj.get('mjai_log') or [])}")
print()

entries = [e for k in rev["kyokus"] for e in k["entries"]]
print(f"decisions: {len(entries)}")

sums = []
for e in entries:
    sums.append(sum(d["prob"] for d in e["details"]))
print(f"prob sum: min={min(sums):.6f} max={max(sums):.6f} mean={sum(sums)/len(sums):.6f}")
print()

# does the argmax of details equal `expected`?
mismatch = 0
for e in entries:
    top = max(e["details"], key=lambda d: d["prob"])["action"]
    if top != e["expected"]:
        mismatch += 1
print(f"argmax(details) == expected : {len(entries)-mismatch}/{len(entries)}")
print()

eq = sum(1 for e in entries if e["is_equal"])
print(f"is_equal count : {eq}/{len(entries)} = {100.0*eq/len(entries):.2f}%")
print(f"filename says  : 77.3%  (167/216)")
print()

# sample a decision to show the shape
e = entries[0]
print("=== first decision ===")
print(json.dumps({k: e[k] for k in ("junme", "tiles_left", "actual",
                                   "expected", "is_equal")},
                 ensure_ascii=False, indent=1))
print("details (top 4):")
for d in sorted(e["details"], key=lambda d: -d["prob"])[:4]:
    print(f"   {d['action']}  prob={d['prob']:.6f}")
