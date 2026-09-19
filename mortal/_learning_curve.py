#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Is the limit DATA, or the objective/model?

If val agreement keeps rising as the number of training games grows, the model
is data-starved and more hall-of-fame games would help.  If it flattens, the
current 62k decisions already saturate what this model can learn, and further
effort should go elsewhere (objective, features, or accepting the noise floor).

Each run trains for exactly ONE epoch on its subset of the TRAIN split, so the
comparison measures the value of data, not of extra steps.  The val split is
never trained on.
"""
from __future__ import annotations

import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

FRACS = [0.25, 0.50, 1.00]
outs = []
for f in FRACS:
    tag = f'{int(f*100):03d}'
    out = f'../reviewer/out/_lc_{tag}.pth'
    cmd = [sys.executable, 'distill.py', '--tau', '1.0', '--w-hard', '1.0',
           '--w-distill', '1.0', '--lr', '1e-5',
           '--state-file', '../backups/before_distill_321275.pth',
           '--split', 'train', '--train-frac', str(f), '--epochs', '1',
           '--save-every', '1000000', '--num-workers', '2', '--out', out]
    print(f'=== training on {tag}% of the train split ===', flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    lines = [l for l in (r.stdout or '').splitlines()
             if 'train-frac' in l or 'kd-loss' in l]
    for l in lines[:1] + lines[-1:]:
        print('   ', l.split('INFO', 1)[-1].strip())
    if r.returncode != 0:
        print('    FAILED:', (r.stderr or '')[-500:])
    outs.append((tag, out))

print()
print('=== val agreement vs training-set size ===')
cmd = [sys.executable, 'eval_distill.py', '../backups/before_distill_321275.pth']
cmd += [o for _, o in outs]
cmd += ['--split', 'val', '--num-workers', '2']
r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                   errors='replace')
print(r.stdout[-2200:])
if r.returncode != 0:
    print(r.stderr[-1000:])
