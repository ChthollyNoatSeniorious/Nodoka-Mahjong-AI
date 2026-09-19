#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic train/val split for the distillation set.

Why this matters: the 89.05% top-1 figure was measured on the SAME 416 games
that were trained on, so it is a training-set number and cannot show where
generalisation stops improving.  Finding a real inflection point needs held-out
games.

The split is a pure function of (sorted file list, seed), so `distill.py` and
`eval_distill.py` agree on it without sharing state.
"""
from __future__ import annotations

import random


def split_files(files, val_frac: float = 0.15, seed: int = 20240915):
    """-> (train_files, val_files), deterministic in (files, val_frac, seed)."""
    fs = sorted(files)
    if val_frac <= 0:
        return fs, []
    rng = random.Random(seed)
    order = list(range(len(fs)))
    rng.shuffle(order)
    n_val = max(1, int(round(len(fs) * val_frac)))
    val = sorted(fs[i] for i in order[:n_val])
    val_set = set(val)
    train = [f for f in fs if f not in val_set]
    return train, val
