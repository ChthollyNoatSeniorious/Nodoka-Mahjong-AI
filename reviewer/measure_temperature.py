#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What temperature does the reported pi actually correspond to?

Our own mjai-reviewer JSON contains BOTH `q_value` and `prob` for every
candidate action.  Since prob = softmax(q / tau) over the legal actions, we can
recover tau directly:

    tau = (q_i - q_j) / log(p_i / p_j)

This matters a lot for distillation.  Matching pi requires the student's Q to
have the same SPREAD as the teacher's Q / tau.  If tau is 0.1 and the student's
Q is in points, the student would have to shrink its Q spread by ~10x, which
would destroy its value estimates.
"""
from __future__ import annotations

import json
import math
import pathlib
import statistics
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

p = pathlib.Path(r"reviewer\out\testset\test03_finetune_step321275.json")
obj = json.loads(p.read_text(encoding="utf-8"))
entries = [e for k in obj["review"]["kyokus"] for e in k["entries"]]

print(f"review temperature field : {obj['review'].get('temperature')!r}")
print()

taus = []
q_spreads = []
for e in entries:
    det = e.get("details") or []
    if len(det) < 2:
        continue
    det = sorted(det, key=lambda d: -d["prob"])
    qs = [d.get("q_value") for d in det]
    ps = [d.get("prob") for d in det]
    if any(q is None for q in qs) or any((x or 0) <= 0 for x in ps):
        continue
    q_spreads.append(max(qs) - min(qs))
    # use the top two for a stable estimate
    dq = qs[0] - qs[1]
    dp = math.log(ps[0] / ps[1])
    if abs(dp) > 1e-6 and dq > 0:
        taus.append(dq / dp)

print(f"decisions usable: {len(taus)}")
print()
if taus:
    print("=== implied temperature tau = dq / log(p1/p2) ===")
    print(f"  median : {statistics.median(taus):.4f}")
    print(f"  mean   : {statistics.mean(taus):.4f}")
    q = sorted(taus)
    print(f"  p25/p75: {q[len(q)//4]:.4f} / {q[3*len(q)//4]:.4f}")
print()
print("=== Q spread (max-min over legal actions), in Mortal's units ===")
if q_spreads:
    print(f"  median : {statistics.median(q_spreads):.4f}")
    print(f"  mean   : {statistics.mean(q_spreads):.4f}")
    print(f"  min/max: {min(q_spreads):.4f} / {max(q_spreads):.4f}")
print()
print("=== interpretation ===")
if taus:
    t = statistics.median(taus)
    print(f"  If tau ~ {t:.3f}, then to match pi the student's Q spread must be")
    print(f"  roughly the teacher's Q spread (about {statistics.median(q_spreads):.2f} points)")
    print(f"  divided by tau = {statistics.median(q_spreads)/t:.2f}.")
print()
# show a raw example so the numbers are auditable
for e in entries:
    det = sorted((e.get("details") or []), key=lambda d: -d["prob"])
    if len(det) >= 2 and det[0].get("q_value") is not None:
        print("=== example decision ===")
        for d in det[:4]:
            print(f"   q={d['q_value']:+.6f}  prob={d['prob']:.6f}  {d['action']}")
        dq = det[0]["q_value"] - det[1]["q_value"]
        dp = math.log(det[0]["prob"] / det[1]["prob"])
        print(f"   dq={dq:.6f}  log(p1/p2)={dp:.6f}  -> tau={dq/dp:.4f}")
        break
