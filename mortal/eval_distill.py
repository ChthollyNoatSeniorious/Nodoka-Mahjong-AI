#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evaluate a checkpoint against Akino Hana's policy on the distillation set.

This is the instrument that decides whether distillation worked.  It measures,
over the SAME fixed set of decisions for every checkpoint:

  * top-1 agreement   : does the student pick Akino Hana's first choice?
  * KL(teacher||student) : how close is the whole distribution?
  * agreement broken down by how contested the decision is.  This is the key
    diagnostic: on near-ties (teacher top-1 < 40%) a one-hot model cannot do
    well, so improvement THERE is the only proof that the distribution (the
    2nd/3rd choices) was actually learned.

Run from the `mortal` directory:

    ..\\.venv\\Scripts\\python.exe eval_distill.py <checkpoint.pth> [<more.pth> ...]
"""

from __future__ import annotations

import argparse
import os
import sys
from glob import glob

import numpy as np
import torch
from torch.utils.data import DataLoader

from config import config
from dataloader import DistillDatasetsIter
from model import Brain, DQN

BANDS = [(0, 40), (40, 60), (60, 80), (80, 101)]


def load_state(p):
    try:
        return torch.load(p, weights_only=True, map_location='cpu')
    except Exception:
        return torch.load(p, weights_only=False, map_location='cpu')


@torch.inference_mode()
def evaluate(ckpt, files, targets, device, tau=0.1, enable_amp=True,
             batch_size=64, num_workers=2):
    state = load_state(ckpt)
    cfg = state.get('config', config)
    version = cfg['control'].get('version', 4)
    mortal = Brain(version=version, **cfg['resnet']).to(device).eval()
    dqn = DQN(version=version).to(device).eval()
    mortal.load_state_dict(state['mortal'])
    dqn.load_state_dict(state['current_dqn'])

    # a fresh dataset per checkpoint: IterableDataset caches its iterator
    ds = DistillDatasetsIter(version=version, files=files, targets=targets,
                             num_epochs=1)
    loader = DataLoader(ds, batch_size=batch_size, num_workers=num_workers)

    n = 0
    top1 = 0
    kl = 0.0
    band_n = {b: 0 for b in BANDS}
    band_ok = {b: 0 for b in BANDS}

    for obs, mask, target in loader:
        obs = obs.to(device=device, dtype=torch.float32)
        mask = mask.to(device=device, dtype=torch.bool)
        target = target.to(device=device, dtype=torch.float32)
        with torch.autocast(device.type, enabled=enable_amp):
            q = dqn(mortal(obs), mask)
        q32 = q.float()
        logp = torch.log_softmax(q32 / tau, dim=-1)

        pred = q32.argmax(-1)
        gold = target.argmax(-1)
        ok = (pred == gold)
        top1 += int(ok.sum())

        # KL(teacher || student).  Illegal actions have logp = -inf while the
        # teacher has zero mass there, and 0 * inf is nan -- so sanitise logp
        # BEFORE doing any arithmetic with it.
        t = target.clamp_min(0)
        pos = t > 0
        # clamp_min(-50) turns any -inf into a large-but-finite value so the
        # metric stays comparable instead of saturating at inf
        logp_safe = torch.where(pos, logp.clamp_min(-50.0),
                                torch.zeros_like(logp))
        terms = torch.where(
            pos,
            t * (torch.log(t.clamp_min(1e-12)) - logp_safe),
            torch.zeros_like(t),
        )
        kl += float(terms.sum())

        conf = target.max(-1).values * 100.0
        for lo, hi in BANDS:
            sel = (conf >= lo) & (conf < hi)
            band_n[(lo, hi)] += int(sel.sum())
            band_ok[(lo, hi)] += int((ok & sel).sum())
        n += int(obs.shape[0])

    return {
        'n': n,
        'top1': top1 / max(1, n),
        'kl': kl / max(1, n),
        'bands': {b: (band_ok[b], band_n[b]) for b in BANDS},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('checkpoints', nargs='+')
    ap.add_argument('--distill-dir', default='./distill')
    ap.add_argument('--batch-size', type=int, default=64)
    ap.add_argument('--limit', type=int, default=0,
                    help='only use the first N games (faster)')
    ap.add_argument('--split', choices=['all', 'train', 'val'], default='val',
                    help='which part of the split to measure.  "val" is the '
                         'honest choice: those games were never trained on')
    ap.add_argument('--val-frac', type=float, default=0.15)
    ap.add_argument('--split-seed', type=int, default=20240915)
    ap.add_argument('--num-workers', type=int, default=2)
    ap.add_argument('--tau', type=float, default=0.1)
    args = ap.parse_args()

    blob = load_state(os.path.join(args.distill_dir, 'targets.pt'))
    targets = blob['games']
    files = sorted(glob(os.path.join(args.distill_dir, 'logs', '*.json.gz')))
    if args.limit:
        files = files[:args.limit]
    if args.split != 'all':
        from distill_split import split_files
        train, val = split_files(files, args.val_frac, args.split_seed)
        files = train if args.split == 'train' else val
    print(f'distill set: {len(files)} logs ({args.split}), '
          f'{len(targets)} target records')
    print()

    version = 4
    device = torch.device(config['control']['device'])
    amp = bool(config['control'].get('enable_amp', True))

    hdr = (f'{"checkpoint":34} {"N":>7} {"top1":>8} {"KL":>8}   '
           + '  '.join(f'pi{lo}-{hi if hi<=100 else 100}' for lo, hi in BANDS))
    print(hdr)
    print('-' * len(hdr))
    for ck in args.checkpoints:
        r = evaluate(ck, files, targets, device, tau=args.tau, enable_amp=amp,
                     batch_size=args.batch_size, num_workers=args.num_workers)
        name = os.path.basename(ck)[:34]
        cells = []
        for b in BANDS:
            ok, tot = r['bands'][b]
            cells.append(f'{100.0*ok/tot:6.1f}%' if tot else '    n/a')
        print(f'{name:34} {r["n"]:>7} {100*r["top1"]:>7.2f}% {r["kl"]:>8.4f}   '
              + '  '.join(cells))
    print()
    print('top1  = student picks the teacher\'s first choice')
    print('KL    = KL(teacher || student); lower is a closer full distribution')
    print('bands = agreement grouped by the teacher\'s own top-1 confidence')
    print('        the low bands are where learning the 2nd/3rd choices pays off')
    return 0


if __name__ == '__main__':
    sys.exit(main())
