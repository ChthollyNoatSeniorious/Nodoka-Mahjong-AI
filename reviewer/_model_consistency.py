"""Are all 10 test-set reports from the SAME model?

If bigcoach swapped the model at some point, the pi distributions across the
test-set files will differ systematically: an older, sharper model gives pi~100
almost everywhere, a newer one gives spread-out pi.

This matters enormously: our 1765 training logs and the Test-set baseline were
produced by whatever model existed THEN.  If the model on bigcoach NOW is a
different one, distilling from it trains toward a different target than the one
we measure against.

We cannot date the files from content, but we CAN compare their statistics.  A
model swap shows up as a step change in pi sharpness.  We also use the file
mtime as a weak proxy for collection order.
"""
from __future__ import annotations

import importlib.util
import math
import pathlib
import statistics
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cmp", HERE / "compare_test03.py")
cmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp)

files = sorted(cmp.TESTSET.glob("test*.htm"))
print("=== per-file pi sharpness ===")
print()
hdr = "%-8s %-12s %8s %9s %10s %10s %9s" % (
    "case", "mtime", "n", "mean top1", "mean H", "eff#act", "top1>=90%")
print(hdr)
print("-" * len(hdr))

rows = []
for f in files:
    tag = f.name.split("_")[0]
    mt = time.strftime("%m-%d %H:%M", time.localtime(f.stat().st_mtime))
    entries = [e for k in cmp.parse_akino(f) for e in k]
    top1s, ents, neff = [], [], []
    n90 = 0
    for e in entries:
        ps = [c["pi"] / 100.0 for c in e["cands"] if c["pi"] > 0]
        if not ps:
            continue
        t = max(ps)
        top1s.append(t)
        if t >= 0.9:
            n90 += 1
        h = -sum(p * math.log(p) for p in ps)
        ents.append(h)
        neff.append(math.exp(h))
    rows.append((tag, f.stat().st_mtime, statistics.mean(top1s),
                 statistics.mean(ents), statistics.mean(neff),
                 n90 / len(entries)))
    print("%-8s %-12s %8d %8.2f%% %9.4f %10.2f %8.1f%%" % (
        tag, mt, len(entries), 100 * statistics.mean(top1s),
        statistics.mean(ents), statistics.mean(neff),
        100 * n90 / len(entries)))

print()
print("=== interpretation ===")
tops = [r[2] for r in rows]
print(f"  mean top-1 across files : {100*statistics.mean(tops):.2f}%")
print(f"  spread (stdev)          : {100*statistics.stdev(tops):.2f} pts")
print(f"  min / max               : {100*min(tops):.2f}% / {100*max(tops):.2f}%")
print()
if statistics.stdev(tops) < 0.05:
    print("  => all files look like the SAME model (consistent sharpness).")
else:
    print("  => sharpness varies a lot; check whether a model swap happened")
    print("     partway through collection (compare the mtime ordering above).")
