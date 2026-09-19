#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where does the distillation speed go? (3.2 it/s -> 0.3 it/s)

Hypotheses:
  1. memory leak -> swap.  The dataloader materialises a whole game at once:
     take_obs() returns ~130 x (1012,34) float32 per player, and libriichi
     returns all four players = ~70 MB per log file.  With num_workers>0 and
     prefetching, several files are in flight.
  2. the per-file GameplayLoader is rebuilt constantly (minor).
  3. GPU is idle waiting on the loader (likely, given the CPU work is heavy).

This measures the raw loader throughput alone, then with the model, and reports
process RSS so a leak is visible.
"""
from __future__ import annotations

import gc
import os
import sys
import time
from glob import glob

import torch
from torch.utils.data import DataLoader

from config import config
from dataloader import DistillDatasetsIter

try:
    import psutil
except ImportError:
    psutil = None


def rss_mb():
    if psutil is None:
        return -1
    return psutil.Process(os.getpid()).memory_info().rss / 1e6


blob = torch.load(os.path.join("distill", "targets.pt"), weights_only=False)
targets = blob["games"]
files = sorted(glob(os.path.join("distill", "logs", "*.json.gz")))[:12]
print(f"logs for this test: {len(files)}")
print()

for nw in (0, 2):
    ds = DistillDatasetsIter(version=4, files=files, targets=targets, num_epochs=1)
    it = iter(DataLoader(ds, batch_size=32, num_workers=nw))
    n = 0
    t0 = time.time()
    marks = []
    for batch in it:
        n += 1
        if n % 50 == 0:
            el = time.time() - t0
            marks.append((n, n / el, rss_mb()))
        if n >= 300:
            break
    el = time.time() - t0
    print(f"=== num_workers={nw} : {n} batches in {el:.1f}s = {n/el:.2f} it/s (loader only)")
    for b, rate, r in marks:
        print(f"    after {b:>4} batches: {rate:5.2f} it/s   RSS {r:,.0f} MB")
    del it, ds
    gc.collect()
    print()

# now with the model on GPU
from model import Brain, DQN
state = torch.load("../backups/before_distill_321275.pth", map_location="cpu",
                   weights_only=False)
device = torch.device(config["control"]["device"])
mortal = Brain(version=4, **config["resnet"]).to(device).eval()
dqn = DQN(version=4).to(device).eval()
mortal.load_state_dict(state["mortal"])
dqn.load_state_dict(state["current_dqn"])

ds = DistillDatasetsIter(version=4, files=files, targets=targets, num_epochs=1)
it = iter(DataLoader(ds, batch_size=32, num_workers=2))
n = 0
t0 = time.time()
marks = []
with torch.inference_mode():
    for obs, mask, target in it:
        obs = obs.to(device=device, dtype=torch.float32)
        mask = mask.to(device=device, dtype=torch.bool)
        with torch.autocast(device.type, enabled=True):
            q = dqn(mortal(obs), mask)
        n += 1
        if n % 50 == 0:
            el = time.time() - t0
            marks.append((n, n / el, rss_mb()))
        if n >= 300:
            break
el = time.time() - t0
print(f"=== loader + GPU forward : {n} batches in {el:.1f}s = {n/el:.2f} it/s")
for b, rate, r in marks:
    print(f"    after {b:>4} batches: {rate:5.2f} it/s   RSS {r:,.0f} MB")
