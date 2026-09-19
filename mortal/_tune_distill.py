#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Why does distillation at tau=0.1 destroy the model, and what fixes it?

Measured facts:
  * the reported pi is exactly softmax(Q / 0.1)   [measure_temperature.py]
  * the teacher's Q spread is ~7.8 points
  * so with tau = 0.1 the logits span ~78, i.e. pi is essentially one-hot with a
    short tail.  Matching it requires the student's Q to agree with the teacher's
    Q to within a few hundredths of a point -- and the gradient scales as 1/tau,
    so steps are 10x larger than at tau = 1.

Observed: 160 steps at tau=0.1, lr=1e-5 dropped top-1 agreement 79.05% -> 62.12%.

This runs short controlled trials and reports which setting is stable.  Each
trial is ~160 optimizer steps.
"""
from __future__ import annotations

import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

TRIALS = [
    ("tau0.1_lr1e-5", ["--tau", "0.1", "--lr", "1e-5"]),
    ("tau0.1_lr1e-6", ["--tau", "0.1", "--lr", "1e-6"]),
    ("tau0.5_lr1e-5", ["--tau", "0.5", "--lr", "1e-5"]),
    ("tau1.0_lr1e-5", ["--tau", "1.0", "--lr", "1e-5"]),
    ("tau1.0_lr1e-6", ["--tau", "1.0", "--lr", "1e-6"]),
]

STEPS = 160
outs = []
for name, extra in TRIALS:
    out = f"../reviewer/out/_trial_{name}.pth"
    cmd = [sys.executable, "distill.py", "--limit", str(STEPS),
           "--save-every", "1000000", "--num-workers", "0",
           "--out", out] + extra
    print(f"=== {name} ===", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    tail = [l for l in (r.stdout or "").splitlines() if "loss" in l]
    for l in tail[-3:]:
        print("   ", l.split("INFO", 1)[-1].strip())
    outs.append((name, out))

print()
print("=== evaluating each trial (baseline 321k = 79.05% top1) ===")
cmd = [sys.executable, "eval_distill.py", "../backups/before_distill_321275.pth"]
cmd += [o for _, o in outs]
cmd += ["--limit", "40", "--num-workers", "0"]
r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                   errors="replace")
print(r.stdout[-2500:])
if r.returncode != 0:
    print(r.stderr[-1500:])
