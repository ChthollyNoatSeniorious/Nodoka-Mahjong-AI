#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Which objective actually improves top-1 agreement?

Established by measurement:
  * the reported pi is softmax(Q/0.1); the teacher's Q spread is ~7.8 points
  * training on it at tau=0.1 degrades EVERY confidence band, monotonically
    (top-1 78.9% -> 64.0% over 1725 steps at lr=1e-6), so the loss is being
    reduced by flattening Q rather than by matching the policy.

This compares objectives over an equal number of steps from the same starting
checkpoint, and reports the metric that matters: top-1 agreement, especially in
the high-confidence band (which must NOT fall) and the near-tie band (the only
place the 2nd/3rd-choice information can show up).
"""
from __future__ import annotations

import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

STEPS = 1200
TRIALS = [
    ("soft tau0.1 only", ["--tau", "0.1", "--w-hard", "0", "--lr", "1e-6"]),
    ("soft tau1.0 + hard", ["--tau", "1.0", "--w-hard", "1.0", "--lr", "1e-5"]),
    ("hard only", ["--tau", "1.0", "--w-hard", "1.0", "--w-distill", "0",
                   "--lr", "1e-5"]),
    ("soft tau1.0 only", ["--tau", "1.0", "--w-hard", "0", "--lr", "1e-6"]),
]

outs = []
for name, extra in TRIALS:
    out = f"../reviewer/out/_obj_{name.replace(' ', '_').replace('.', '')}.pth"
    cmd = [sys.executable, "distill.py", "--limit", str(STEPS),
           "--save-every", "1000000", "--num-workers", "2", "--out", out] + extra
    print(f"=== {name} ===", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    lines = [l for l in (r.stdout or "").splitlines() if "loss" in l]
    for l in lines[-2:]:
        print("   ", l.split("INFO", 1)[-1].strip())
    if r.returncode != 0:
        print("    FAILED:", (r.stderr or "")[-400:])
    outs.append((name, out))

print()
print("=== evaluation (baseline = 78.9% top1, 52.1% near-tie) ===")
cmd = [sys.executable, "eval_distill.py", "../backups/before_distill_321275.pth"]
cmd += [o for _, o in outs]
cmd += ["--limit", "40", "--num-workers", "0"]
r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                   errors="replace")
print(r.stdout[-2600:])
if r.returncode != 0:
    print(r.stderr[-1200:])
