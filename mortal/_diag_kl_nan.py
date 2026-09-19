#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Why is the KL nan?

Suspicion: some rows have an all-False mask, which makes `q` entirely -inf and
`log_softmax` produce nan.  An all-False mask would also make argmax meaningless.
"""
from __future__ import annotations

import os
import sys
from glob import glob

import numpy as np
import torch
from torch.utils.data import DataLoader

from config import config
from dataloader import DistillDatasetsIter

blob = torch.load(os.path.join("distill", "targets.pt"), weights_only=False)
targets = blob["games"]
files = sorted(glob(os.path.join("distill", "logs", "*.json.gz")))[:20]

ds = DistillDatasetsIter(version=4, files=files, targets=targets, num_epochs=1)
loader = DataLoader(ds, batch_size=64, num_workers=0)

n = 0
empty_mask = 0
tgt_sum_bad = 0
tgt_on_illegal = 0
mass_illegal = 0.0
rows_illegal = 0

for obs, mask, target in loader:
    n += int(obs.shape[0])
    msum = mask.sum(-1)
    empty_mask += int((msum == 0).sum())
    s = target.sum(-1)
    tgt_sum_bad += int((s < 0.99).sum() | (s > 1.01).sum())
    # target mass sitting on illegal actions
    illegal = target * (~mask).float()
    bad = illegal.sum(-1)
    rows_illegal += int((bad > 1e-6).sum())
    mass_illegal += float(bad.sum())
    tgt_on_illegal += int((bad > 1e-6).sum())

print(f"rows checked          : {n:,}")
print(f"rows with empty mask  : {empty_mask}")
print(f"rows with target sum != 1 : {tgt_sum_bad}")
print(f"rows with target mass on ILLEGAL actions : {rows_illegal}"
      f"  (total mass {mass_illegal:.4f})")
print()
print("If 'empty mask' is 0 and 'illegal mass' is 0, the KL nan must come from")
print("elsewhere (e.g. 0*inf inside the term before the where()).")
