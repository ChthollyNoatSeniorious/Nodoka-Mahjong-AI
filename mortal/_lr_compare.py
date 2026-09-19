#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Last free lever: is lr=1e-5 memorising instead of generalising?

The train/val gap is large (~93.5% train vs ~83.5% val), so the 354 training
games are being partly memorised.  A gentler, longer schedule is the classic
free fix; if it helps, it costs nothing.

Compared at equal opportunity, on the clean val split:
    lr 1e-5, 1 epoch   (the current setting, = 83.5%)
    lr 3e-6, 2 epochs  (same-ish total movement, spread out)
    lr 1e-5, 1 epoch + weight_decay 0.3 (stronger shrinkage)
"""
from __future__ import annotations

import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

RUNS = [
    ("lr3e-6 x2ep", ["--lr", "3e-6", "--epochs", "2"]),
    ("lr1e-5 x1ep", ["--lr", "1e-5", "--epochs", "1"]),
    ("lr3e-5 x1ep", ["--lr", "3e-5", "--epochs", "1"]),
]

outs = []
for name, extra in RUNS:
    tag = name.replace(" ", "").replace("-", "")
    out = f"../reviewer/out/_lr_{tag}.pth"
    cmd = [sys.executable, "distill.py", "--tau", "1.0", "--w-hard", "1.0",
           "--w-distill", "1.0",
           "--state-file", "../backups/before_distill_321275.pth",
           "--split", "train", "--save-every", "1000000",
           "--num-workers", "2", "--out", out] + extra
    print(f"=== {name} ===", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    lines = [l for l in (r.stdout or "").splitlines() if "kd-loss" in l]
    for l in lines[-1:]:
        print("   ", l.split("INFO", 1)[-1].strip())
    if r.returncode != 0:
        print("    FAILED:", (r.stderr or "")[-400:])
    outs.append((name, out))

print()
print("=== clean val agreement ===")
cmd = [sys.executable, "eval_distill.py", "../backups/before_distill_321275.pth"]
cmd += [o for _, o in outs]
cmd += ["--split", "val", "--num-workers", "2"]
r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                   errors="replace")
print(r.stdout[-2000:])
if r.returncode != 0:
    print(r.stderr[-800:])
