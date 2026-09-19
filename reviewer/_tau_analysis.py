"""Can we RECOVER tau from the report itself? (and does it even matter?)

The report shows pi_tau(a|s) = softmax(q / tau).  We do not know tau.

Two questions:
 Q1. Is the reported pi consistent with being a softmax of SOME q at a single
     temperature?  If the numbers are heavily quantised or clipped, tau may be
     unrecoverable -- and more importantly, the target may be distorted.
 Q2. Does the choice of tau actually matter for distillation?

For Q2 the key realisation is that we do NOT need the raw q values.  We need a
target DISTRIBUTION.  If bigcoach reports softmax(q/tau) for an unknown tau,
then training on that pi teaches the model to match softmax(q/tau) -- which is a
strictly *softer* or *sharper* version of Akino Hana, but still the same argmax
and still far more informative than a one-hot label.

What matters is: is tau SHARP (pi nearly one-hot -> little extra info, but also
little harm) or SOFT (pi spread -> much more info, and we must not over-sharpen)?
This script measures how spread the reported pi actually is.
"""
from __future__ import annotations

import collections
import importlib.util
import math
import pathlib
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cmp", HERE / "compare_test03.py")
cmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp)

all_e = []
for tag in [f"test0{i}" for i in range(1, 10)]:
    htm = next(cmp.TESTSET.glob(f"{tag}_*.htm"))
    all_e += [e for k in cmp.parse_akino(htm) for e in k]

print(f"decisions pooled: {len(all_e)}")
print()

# ---- how spread are the distributions? -----------------------------------
entropies = []
top1s = []
for e in all_e:
    ps = [c["pi"] / 100.0 for c in e["cands"] if c["pi"] > 0]
    if not ps:
        continue
    top1s.append(max(ps))
    entropies.append(-sum(p * math.log(p) for p in ps))

print("=== how much information does the pi carry? ===")
print(f"  mean top-1 pi      : {sum(top1s)/len(top1s)*100:6.2f}%")
print(f"  mean entropy (nats): {sum(entropies)/len(entropies):6.4f}")
print()
print("  interpretation:")
print("    entropy near 0  -> pi ~ one-hot, no extra info beyond argmax")
print("    entropy high    -> pi spread, distillation adds real information")
print()

# distribution of top-1 probability
bands = [(0.9, 1.01, ">=90%  (nearly certain)"),
         (0.7, 0.9, "70-90% (confident)"),
         (0.5, 0.7, "50-70% (leaning)"),
         (0.35, 0.5, "35-50% (contested)"),
         (0.0, 0.35, "<35%   (near tie)")]
print("=== top-1 probability distribution ===")
for lo, hi, lbl in bands:
    n = sum(1 for t in top1s if lo <= t < hi)
    print(f"  {lbl:<26} {n:>5}  ({100.0*n/len(top1s):5.1f}%)")
print()

# how many decisions have a genuine second choice?
second = []
for e in all_e:
    ps = sorted((c["pi"] for c in e["cands"]), reverse=True)
    second.append(ps[1] / 100.0 if len(ps) > 1 else 0.0)
print("=== does a real second choice exist? ===")
for thr in (0.30, 0.20, 0.10, 0.05):
    n = sum(1 for s in second if s >= thr)
    print(f"  second-best pi >= {thr*100:4.0f}% : {n:>5} ({100.0*n/len(second):5.1f}%)")
print()

# ---- multinomial: does 'few candidates' mean few legal actions? -----------
print("=== info beyond argmax, measured as 'effective alternatives' ===")
neff = []
for e in all_e:
    ps = [c["pi"] / 100.0 for c in e["cands"] if c["pi"] > 0]
    if not ps:
        continue
    neff.append(math.exp(-sum(p * math.log(p) for p in ps)))
import statistics
print(f"  mean effective #actions : {statistics.mean(neff):.2f}")
print(f"  median                  : {statistics.median(neff):.2f}")
print()
n_gt1 = sum(1 for x in neff if x > 1.2)
print(f"  decisions with effective alternatives > 1.2 : "
      f"{n_gt1} ({100.0*n_gt1/len(neff):.1f}%)")
print()
print("  => these are the decisions where distillation beats one-hot training.")
print("     the rest are effectively argmax anyway.")
