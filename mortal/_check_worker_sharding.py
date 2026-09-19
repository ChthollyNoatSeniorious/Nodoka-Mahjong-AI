#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Measure the duplicate-read problem in DistillDatasetsIter.

PyTorch's DataLoader splits work between workers automatically ONLY for
map-style datasets.  For an **IterableDataset** it does not: every worker runs
`__iter__` over the WHOLE dataset, so with num_workers=2 the data is delivered
twice (equivalent to 2 epochs over duplicated samples), wasting half the compute.

`FileDatasetsIter` avoids this because train.py passes `worker_init_fn`, which
slices `dataset.file_list` per worker.  `DistillDatasetsIter` has no such
sharding yet.

This counts the batches actually produced for the same 8 logs at 0/1/2 workers.
If 2 workers give ~2x the batches of 1 worker, the duplication is confirmed.
"""
from __future__ import annotations

import os
import sys
from glob import glob

import torch
from torch.utils.data import DataLoader

from dataloader import DistillDatasetsIter


def main() -> int:
    blob = torch.load(os.path.join("distill", "targets.pt"), weights_only=False)
    targets = blob["games"]
    files = sorted(glob(os.path.join("distill", "logs", "*.json.gz")))[:8]
    print(f"logs used: {len(files)}")
    print()

    results = {}
    for nw in (0, 1, 2):
        ds = DistillDatasetsIter(version=4, files=files, targets=targets,
                                 num_epochs=1)
        loader = DataLoader(ds, batch_size=32, num_workers=nw)
        n = 0
        samples = 0
        for obs, mask, target in loader:
            n += 1
            samples += int(obs.shape[0])
        results[nw] = (n, samples)
        print(f"num_workers={nw}: {n:>3} batches, {samples:>5} samples delivered")

    print()
    base = results[1][0] if results[1][0] else results[0][0]
    for nw in (1, 2):
        if nw in results and results[nw][0]:
            print(f"num_workers={nw} vs 1 : {results[nw][0]/base:.2f}x batches")
    print()
    if results[2][0] > results[1][0] * 1.8:
        print("=> CONFIRMED: each worker iterates the whole dataset (duplicated).")
        print("   Fix: shard `files` per worker inside build_iter().")
    else:
        print("=> no duplication detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
