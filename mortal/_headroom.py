#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How much room is actually left?

Two questions decide whether more work can help:

1. NOISE FLOOR -- are the remaining disagreements real mistakes, or coin flips?
   Bin every held-out decision by the teacher's own top1-top2 margin.  If nearly
   all disagreements sit in the tiny-margin bins, the teacher itself barely
   distinguishes those actions and no model can reliably match its argmax there.
   The 'oracle' row shows the score if every margin above a threshold were
   matched perfectly, i.e. the ceiling implied by the current data.

2. Whether we are matching the teacher better than the teacher matches humans --
   a sanity reference for how much signal is even present.

Run from the `mortal` directory:
    ..\\.venv\\Scripts\\python.exe _headroom.py <checkpoint> [--split val]
"""
from __future__ import annotations

import argparse
import os
import sys
from glob import glob

import torch
from torch.utils.data import DataLoader

from config import config
from dataloader import DistillDatasetsIter
from model import Brain, DQN

BINS = [(0.0, 0.02), (0.02, 0.05), (0.05, 0.10), (0.10, 0.20),
        (0.20, 0.40), (0.40, 1.01)]


def load_state(p):
    try:
        return torch.load(p, weights_only=True, map_location='cpu')
    except Exception:
        return torch.load(p, weights_only=False, map_location='cpu')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('checkpoint')
    ap.add_argument('--distill-dir', default='./distill')
    ap.add_argument('--split', choices=['all', 'train', 'val'], default='val')
    ap.add_argument('--val-frac', type=float, default=0.15)
    ap.add_argument('--split-seed', type=int, default=20240915)
    ap.add_argument('--batch-size', type=int, default=64)
    ap.add_argument('--num-workers', type=int, default=2)
    ap.add_argument('--tau', type=float, default=0.1)
    args = ap.parse_args()

    blob = load_state(os.path.join(args.distill_dir, 'targets.pt'))
    targets = blob['games']
    files = sorted(glob(os.path.join(args.distill_dir, 'logs', '*.json.gz')))
    if args.split != 'all':
        from distill_split import split_files
        tr, va = split_files(files, args.val_frac, args.split_seed)
        files = tr if args.split == 'train' else va

    state = load_state(args.checkpoint)
    cfg = state.get('config', config)
    version = cfg['control'].get('version', 4)
    device = torch.device(config['control']['device'])
    mortal = Brain(version=version, **cfg['resnet']).to(device).eval()
    dqn = DQN(version=version).to(device).eval()
    mortal.load_state_dict(state['mortal'])
    dqn.load_state_dict(state['current_dqn'])

    ds = DistillDatasetsIter(version=version, files=files, targets=targets,
                             num_epochs=1)
    loader = DataLoader(ds, batch_size=args.batch_size,
                        num_workers=args.num_workers)

    n = 0
    match = 0
    bin_n = {b: 0 for b in BINS}
    bin_bad = {b: 0 for b in BINS}
    # oracle: agreement if every decision with margin >= t is matched
    oracle_hits = {t: 0 for t in (0.02, 0.05, 0.10, 0.20, 0.40)}
    oracle_tot = {t: 0 for t in (0.02, 0.05, 0.10, 0.20, 0.40)}
    sum_top1 = 0.0
    entropy = 0.0

    with torch.inference_mode():
        for obs, mask, target in loader:
            obs = obs.to(device=device, dtype=torch.float32)
            mask = mask.to(device=device, dtype=torch.bool)
            target = target.to(device=device, dtype=torch.float32)
            with torch.autocast(device.type, enabled=True):
                q = dqn(mortal(obs), mask)
            q32 = q.float()
            pred = q32.argmax(-1)
            gold = target.argmax(-1)
            ok = (pred == gold)

            top2 = target.topk(2, dim=-1).values
            margin = top2[:, 0] - top2[:, 1]
            sum_top1 += float(top2[:, 0].sum())
            t = target.clamp_min(1e-12)
            entropy += float(-(t * t.log()).sum())

            n += int(obs.shape[0])
            match += int(ok.sum())
            for lo, hi in BINS:
                sel = (margin >= lo) & (margin < hi)
                bin_n[(lo, hi)] += int(sel.sum())
                bin_bad[(lo, hi)] += int((sel & ~ok).sum())
            for th in oracle_hits:
                sel = margin >= th
                oracle_tot[th] += int(sel.sum())
                oracle_hits[th] += int((sel & ok).sum())

    print(f'checkpoint : {os.path.basename(args.checkpoint)}   split={args.split}')
    print(f'decisions  : {n:,}')
    print(f'top-1      : {100*match/n:.2f}%')
    print(f'mean pi(top1) : {100*sum_top1/n:.2f}%   '
          f'(chance level if you SAMPLED from pi)')
    print(f'mean entropy  : {entropy/n:.4f} nats')
    print()
    print('=== disagreement by the teacher\'s own top1-top2 margin ===')
    print(f'{"margin":>12} {"N":>7} {"share":>7} {"wrong":>7} {"wrong%":>8}   '
          f'{"of all errors":>14}')
    tot_bad = n - match
    for lo, hi in BINS:
        if not bin_n[(lo, hi)]:
            continue
        nb, nbad = bin_n[(lo, hi)], bin_bad[(lo, hi)]
        share = 100.0 * nb / n
        wr = 100.0 * nbad / nb
        contrib = 100.0 * nbad / max(1, tot_bad)
        print(f'{lo:5.2f}-{hi:5.2f} {nb:>7,} {share:>6.1f}% {nbad:>7,} '
              f'{wr:>7.1f}%   {contrib:>13.1f}%')
    print()
    print('=== ceiling implied by the data ===')
    for th in sorted(oracle_hits):
        sel = sum(1 for lo, hi in BINS if lo >= th for _ in [0])
        nb = oracle_tot[th]
        if not nb:
            continue
        acc = 100.0 * oracle_hits[th] / nb
        print(f'  if every margin >= {th:.2f} were matched perfectly: '
              f'{acc:5.1f}% on the {100.0*nb/n:4.1f}% of decisions it covers')
    print()
    print('Reading: if the errors pile up in the smallest-margin bins, the rest')
    print('is close to the noise floor and extra training cannot buy much.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
