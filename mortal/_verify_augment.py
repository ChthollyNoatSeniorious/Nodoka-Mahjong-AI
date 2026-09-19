#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Can we augment the distillation data for free 2x?

The learning curve says the limit is DATA (val agreement still rising linearly
at 354 training games).  Mortal has built-in 180-degree augmentation, which is a
man<->pin swap (libriichi/src/tile.rs: kind 0 -> +9, kind 1 -> -9, sou/honors
untouched, red fives preserved).

If the ACTION SPACE permutes the same way, we can train on the mirrored
observation with a mirrored target and double the effective data for free.

Predicted permutation of the 46 actions:
    0-8   (1m..9m) <-> 9-17 (1p..9p)      because the suits swap
    18-26 (sou), 27-33 (honors)           unchanged
    34 (aka 5m) <-> 35 (aka 5p), 36 (aka 5s) unchanged
    37 reach                              unchanged
    38/39/40 chi low/mid/high             UNCHANGED -- chi type is decided by the
                                          position of the called tile within its
                                          suit (chi_type.rs), and a suit swap
                                          preserves relative position
    41..45 pon/kan/aga/ryukyoku/pass      unchanged

This verifies that claim against real data instead of trusting it: for every
decision the mirrored target must (a) put zero mass on illegal actions and
(b) have a legal argmax, under the MIRRORED mask.
"""
from __future__ import annotations

import os
import sys
from glob import glob

import numpy as np
import torch

from libriichi.dataset import GameplayLoader

ACTION_SPACE = 46
PERM = list(range(ACTION_SPACE))
for _i in range(9):
    PERM[_i], PERM[_i + 9] = _i + 9, _i
PERM[34], PERM[35] = 35, 34


def main() -> int:
    targets = torch.load(os.path.join('distill', 'targets.pt'),
                         weights_only=False)['games']
    files = sorted(glob(os.path.join('distill', 'logs', '*.json.gz')))[:12]
    print(f'checking {len(files)} logs')
    print(f'PERM swaps 0-8 <-> 9-17 and 34 <-> 35; '
          f'involution: {all(PERM[PERM[i]] == i for i in range(ACTION_SPACE))}')
    print()

    n = 0
    bad_mass = 0
    bad_argmax = 0
    miss = 0
    worst = 0.0
    for path in files:
        key = os.path.basename(path)[:-len('.json.gz')]
        rec = targets.get(key)
        if rec is None:
            miss += 1
            continue
        seat = int(key.rsplit('_s', 1)[1])
        for aug in (False, True):
            loader = GameplayLoader(version=4, oracle=False, player_names=[],
                                    excludes=[], augmented=aug)
            for grp in loader.load_gz_log_files([path]):
                for game in grp:
                    if int(game.take_player_id()) != seat:
                        continue
                    masks = game.take_masks()
                    tgt = rec['target']
                    val = rec['valid']
                    for i in range(min(len(masks), len(tgt))):
                        if not bool(val[i]):
                            continue
                        m = torch.as_tensor(np.asarray(masks[i], dtype=bool))
                        t = tgt[i].clone()
                        if aug:
                            t = t[PERM]          # PERM is an involution
                        n += 1
                        illegal = float((t * (~m).float()).sum())
                        if illegal > 1e-6:
                            bad_mass += 1
                            worst = max(worst, illegal)
                        if not bool(m[int(t.argmax())]):
                            bad_argmax += 1
    print(f'rows checked (both frames)   : {n:,}')
    print(f'target records not found     : {miss}')
    print()
    print(f'mass on ILLEGAL actions      : {bad_mass}   (worst {worst:.6f})')
    print(f'argmax ILLEGAL               : {bad_argmax}')
    print()
    if bad_mass == 0 and bad_argmax == 0:
        print('=> augmentation is SAFE: the mirrored target stays inside the')
        print('   mirrored legal set, so training on it is valid.')
    else:
        print('=> NOT safe as-is; the permutation needs correcting.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
