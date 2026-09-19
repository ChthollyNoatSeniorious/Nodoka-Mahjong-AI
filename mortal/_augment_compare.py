#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Does the free 2x augmentation actually buy anything?

The learning curve showed the limit is DATA (val still rising linearly at 354
games).  Real extra games are not available -- the free hall-of-fame pool is
exhausted at 416 -- so the only free lever left is Mortal's 180-degree
augmentation, which doubles the sample count at zero cost.

Caveat this measures: mirrored copies are NOT independent information, so the
gain should be smaller than doubling the real data.  The comparison is against
_lc_100 (same 354 train games, same 1 epoch, no augmentation), so the only
difference is the augmentation.

Training steps double when augmentation is on (2 frames per log), so the two
runs are compared at their own end-of-epoch, which is the honest comparison.
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
    ("no augment (baseline)", []),
    ("augment on", ["--augment"]),
]

outs = []
for name, extra in RUNS:
    tag = "aug" if extra else "noaug"
    out = f"../reviewer/out/_augcmp_{tag}.pth"
    cmd = [sys.executable, "distill.py", "--tau", "1.0", "--w-hard", "1.0",
           "--w-distill", "1.0", "--lr", "1e-5",
           "--state-file", "../backups/before_distill_321275.pth",
           "--split", "train", "--epochs", "1",
           "--save-every", "1000000", "--num-workers", "2", "--out", out] + extra
    print(f"=== {name} ===", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    lines = [l for l in (r.stdout or "").splitlines() if "kd-loss" in l]
    for l in lines[-1:]:
        print("   ", l.split("INFO", 1)[-1].strip())
    if r.returncode != 0:
        print("    FAILED:", (r.stderr or "")[-500:])
    outs.append((name, out))

print()
print("=== val agreement (train split only, so val is clean) ===")
cmd = [sys.executable, "eval_distill.py", "../backups/before_distill_321275.pth"]
cmd += [o for _, o in outs]
cmd += ["--split", "val", "--num-workers", "2"]
r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                   errors="replace")
print(r.stdout[-2000:])
if r.returncode != 0:
    print(r.stderr[-800:])
