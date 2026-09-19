"""Knowledge distillation from Akino Hana (長明 1.4) into the current model.

WHY
---
The training logs only record *which* tile Akino Hana discarded, so the DQN
objective can only learn its argmax.  ~78% of decisions have more than one
plausible choice, and on near-tie decisions (top-1 pi < 40%, about 20% of them)
a one-hot target carries almost no information -- which is why the current model
sits at ~50% agreement there.

The harvested hall-of-fame reviews give the FULL distribution pi(a|s), so we can
train the student to reproduce the whole policy: the top choice first, then the
second and third choices with their proper probabilities.

OBJECTIVE
---------
Mortal produces its policy as softmax(Q / tau) (mortal/engine.py).  We therefore
distil into Q with a temperature-scaled cross entropy:

    loss = -(target * log_softmax(Q / tau)).sum(-1).mean()

The minimum is at softmax(Q/tau) == target.  Since the teacher's pi is itself a
softmax of some Q_teacher, matching requires Q proportional to Q_teacher -- and
a positive rescaling of Q changes neither the argmax nor the ranking, so the
top-1 and the ordering of the 2nd/3rd choices are both preserved regardless of
the exact tau.

A small DQN term is kept as an anchor so the *scale* of Q does not drift away
from what the value head expects.

USAGE (from the `mortal` directory)
-----------------------------------
    ..\\.venv\\Scripts\\python.exe distill.py
    ..\\.venv\\Scripts\\python.exe distill.py --epochs 2 --lr 1e-5
"""

from __future__ import annotations

import argparse
import gc
import logging
import os
import sys
import time
from datetime import datetime
from os import path
from glob import glob

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
from tqdm import tqdm

from config import config
from dataloader import DistillDatasetsIter
from model import Brain, DQN

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)


def load_state(p):
    try:
        return torch.load(p, weights_only=True, map_location='cpu')
    except Exception:
        return torch.load(p, weights_only=False, map_location='cpu')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--distill-dir', default='./distill',
                    help='directory produced by reviewer/export_distill.py')
    ap.add_argument('--state-file', default=None,
                    help='checkpoint to start from (default: config state_file)')
    ap.add_argument('--out', default='./output/my_finetuned_model/mortal.pth')
    ap.add_argument('--epochs', type=int, default=1)
    ap.add_argument('--lr', type=float, default=1e-5)
    ap.add_argument('--tau', type=float, default=1.0,
                    help='soft-target temperature.  The report is at tau=0.1, '
                         'but training at 0.1 is unstable: its gradient scales '
                         'as 1/tau and it demands near-exact Q matching.  A '
                         'larger tau keeps the same optimum (and hence the same '
                         'top-1) while conditioning the gradient')
    ap.add_argument('--batch-size', type=int, default=None)
    ap.add_argument('--w-distill', type=float, default=1.0)
    ap.add_argument('--w-hard', type=float, default=1.0,
                    help="weight on hard top-1 cross entropy against the "
                         "teacher's first choice -- the term that directly "
                         "protects top-1 agreement (the primary goal), while "
                         "the soft term supplies the 2nd/3rd choice info")
    ap.add_argument('--grad-clip', type=float, default=1.0,
                    help='max gradient norm (0 disables)')
    ap.add_argument('--min-q-weight', type=float, default=0.0,
                    help='optional CQL weight; 0 disables it (distillation '
                         'already provides the relative probabilities)')
    ap.add_argument('--save-every', type=int, default=1000)
    ap.add_argument('--snapshot-dir', default=None,
                    help='also write stepN.pth snapshots here, so the trajectory '
                         'of top-1 agreement can be measured')
    ap.add_argument('--num-workers', type=int, default=2)
    ap.add_argument('--split', choices=['all', 'train', 'val'], default='train',
                    help='train on the train split by default, so the val '
                         'games stay unseen and the curve is honest')
    ap.add_argument('--val-frac', type=float, default=0.15)
    ap.add_argument('--split-seed', type=int, default=20240915)
    ap.add_argument('--train-frac', type=float, default=1.0,
                    help='use only this fraction of the training games.  For a '
                         'learning curve: if val keeps improving as this grows, '
                         'the limit is DATA, not the model or the objective')
    ap.add_argument('--augment', action='store_true',
                    help='also replay every log in Mortal 180-degree augmented '
                         'frame (man<->pin swap) with the target permuted by '
                         'ACTION_PERM -- free 2x data')
    ap.add_argument('--limit', type=int, default=0,
                    help='stop after N optimizer steps (smoke test)')
    # ---- phase 2: keep the self-play ability --------------------------- #
    ap.add_argument('--selfplay-globs', default='',
                    help="comma separated globs of the AI's own logs, e.g. "
                         "'./date/*.json.gz'.  Mixing these in keeps the value "
                         "head calibrated and preserves behaviour on positions "
                         "the AI actually reaches, which the hall-of-fame "
                         "(human) games do not cover")
    ap.add_argument('--selfplay-frac', type=float, default=0.0,
                    help='fraction of optimizer steps taken from self-play')
    ap.add_argument('--selfplay-cql', type=float, default=None,
                    help='CQL weight on self-play batches (default: config)')
    args = ap.parse_args()

    torch.manual_seed(20240915)
    np.random.seed(20240915)

    # ---- data ---------------------------------------------------------- #
    tgt_path = path.join(args.distill_dir, 'targets.pt')
    if not path.isfile(tgt_path):
        print(f'no targets at {tgt_path}; run reviewer/export_distill.py first',
              file=sys.stderr)
        return 2
    blob = load_state(tgt_path)
    targets = blob['games']
    meta = blob.get('meta', {})
    log_files = sorted(glob(path.join(args.distill_dir, 'logs', '*.json.gz')))
    from distill_split import split_files
    train_files, val_files = split_files(log_files, args.val_frac,
                                         args.split_seed)
    if args.split == 'train':
        log_files = train_files
    elif args.split == 'val':
        log_files = val_files
    if args.train_frac < 1.0 and args.split != 'val':
        import random as _random
        _rng = _random.Random(args.split_seed)
        _fs = sorted(log_files)
        _rng.shuffle(_fs)
        log_files = sorted(_fs[:max(1, int(round(len(_fs) * args.train_frac)))])
        logging.info(f'train-frac {args.train_frac}: using {len(log_files)} games')
    logging.info(f'distillation set: {meta.get("games")} games, '
                 f'{meta.get("valid_rows"):,} labelled decisions, '
                 f'{len(log_files)} logs '
                 f'(train {len(train_files)} / val {len(val_files)})')
    if not log_files:
        print('no logs found', file=sys.stderr)
        return 2

    # ---- model --------------------------------------------------------- #
    state_file = args.state_file or config['control']['state_file']
    state = load_state(state_file)
    cfg = state.get('config', config)
    version = cfg['control'].get('version', 4)
    resnet = cfg['resnet']

    device = torch.device(config['control']['device'])
    enable_amp = bool(config['control'].get('enable_amp', True))

    mortal = Brain(version=version, **resnet).to(device)
    dqn = DQN(version=version).to(device)
    mortal.load_state_dict(state['mortal'])
    dqn.load_state_dict(state['current_dqn'])
    mortal.train()
    dqn.train()

    steps_done = int(state.get('steps', 0))
    logging.info(f'starting from {state_file} (steps={steps_done:,})')

    params = list(mortal.parameters()) + list(dqn.parameters())
    optimizer = torch.optim.AdamW(
        params, lr=args.lr,
        betas=tuple(config['optim']['betas']),
        eps=config['optim']['eps'],
        weight_decay=config['optim']['weight_decay'],
    )
    scaler = torch.amp.GradScaler(device.type, enabled=enable_amp)
    mse = nn.MSELoss()
    ce = nn.CrossEntropyLoss()

    batch_size = args.batch_size or config['control']['batch_size']
    ds = DistillDatasetsIter(version=version, files=log_files,
                             targets=targets, num_epochs=args.epochs,
                             enable_augmentation=args.augment)
    loader = iter(DataLoader(ds, batch_size=batch_size, drop_last=True,
                             num_workers=args.num_workers, pin_memory=True))

    # ---- optional self-play stream (phase 2) --------------------------- #
    sp_loader = None
    if args.selfplay_globs and args.selfplay_frac > 0:
        from dataloader import FileDatasetsIter, worker_init_fn
        sp_files = []
        for pat in args.selfplay_globs.split(','):
            sp_files.extend(glob(pat.strip(), recursive=True))
        if not sp_files:
            print(f'no self-play logs matched {args.selfplay_globs!r}',
                  file=sys.stderr)
            return 2
        sp_ds = FileDatasetsIter(
            version=version,
            file_list=sp_files,
            pts=config['env']['pts'],
            file_batch_size=config['dataset']['file_batch_size'],
            reserve_ratio=config['dataset']['reserve_ratio'],
            player_names=[],
            num_epochs=args.epochs,
            enable_augmentation=config['dataset'].get('enable_augmentation',
                                                      False),
            augmented_first=config['dataset'].get('augmented_first', False),
        )
        sp_loader = iter(DataLoader(
            sp_ds, batch_size=batch_size, drop_last=True,
            num_workers=max(1, args.num_workers), pin_memory=True,
            worker_init_fn=worker_init_fn,
        ))
        logging.info(f'self-play stream: {len(sp_files)} logs, '
                     f'{100*args.selfplay_frac:.0f}% of steps')

    writer = SummaryWriter(config['control']['tensorboard_dir'])
    out_file = args.out
    steps = steps_done
    t0 = time.time()
    last_log = t0
    run = {'kd': 0, 'sp': 0, 'kd_loss': 0.0, 'sp_loss': 0.0, 'top1': 0.0}

    logging.info(f'tau={args.tau}  w_distill={args.w_distill}  '
                 f'min_q_weight={args.min_q_weight}  lr={args.lr}  '
                 f'batch={batch_size}')

    def save():
        torch.save({
            'mortal': mortal.state_dict(),
            'current_dqn': dqn.state_dict(),
            'aux_net': state.get('aux_net', {}),
            'optimizer': optimizer.state_dict(),
            'scheduler': {},
            'scaler': scaler.state_dict(),
            'steps': steps,
            'timestamp': datetime.now().timestamp(),
            'best_perf': state.get('best_perf', {}),
            'config': cfg,
        }, out_file)
        logging.info(f'saved {out_file} at step {steps:,}')

    def compute_loss(obs, mask, target, batch):
        """Distillation objective (with the optional self-play terms)."""
        obs = obs.to(device=device, dtype=torch.float32)
        mask = mask.to(device=device, dtype=torch.bool)
        target = target.to(device=device, dtype=torch.float32)
        with torch.autocast(device.type, enabled=enable_amp):
            q_out = dqn(mortal(obs), mask)
            # The teacher's support should equal the legal actions, but make
            # that explicit: any target mass on an illegal action would meet
            # -inf and poison the loss with inf/NaN.
            t = (target * mask.float())
            t = t / t.sum(-1, keepdim=True).clamp_min(1e-8)
            # DQN masks illegal actions with -inf, so `t * logp` would be
            # 0 * -inf = NaN; mask BEFORE multiplying.  fp32 too, since
            # dividing by tau sharpens logits and fp16 would lose precision.
            q32 = q_out.float()
            logp = torch.log_softmax(q32 / args.tau, dim=-1)
            safe_logp = torch.where(t > 0, logp, torch.zeros_like(logp))
            distill_loss = -(t * safe_logp).sum(-1).mean()
            distill_loss = torch.nan_to_num(distill_loss, nan=0.0,
                                            posinf=1e4, neginf=0.0)

            loss = args.w_distill * distill_loss

            if args.w_hard > 0:
                # hard top-1 term: directly optimises "does the student pick
                # the teacher's first choice".  Without it the soft term can
                # buy loss reduction by flattening Q, which degrades top-1.
                gold = t.argmax(-1)
                hard_loss = torch.nn.functional.cross_entropy(q32, gold)
                loss = loss + args.w_hard * hard_loss
            if args.min_q_weight > 0:
                q_legal = q32.masked_fill(~mask, 0.0)
                cql = q_legal.logsumexp(-1).mean() - (t * q32).sum(-1).mean()
                loss = loss + args.min_q_weight * cql
        return loss, q_out, t

    def compute_selfplay_loss(batch):
        """Mortal's own offline objective on the AI's self-play positions.

        Keeps the value head calibrated (MC return in points) and preserves
        competence on positions the AI actually reaches -- the hall-of-fame
        games are human positions and do not cover those.
        """
        obs, actions, mask, steps_to_done, kyoku_rewards, player_ranks = batch
        obs = obs.to(device=device, dtype=torch.float32)
        actions = actions.to(device=device, dtype=torch.int64)
        mask = mask.to(device=device, dtype=torch.bool)
        steps_to_done = steps_to_done.to(device=device, dtype=torch.int64)
        kyoku_rewards = kyoku_rewards.to(device=device, dtype=torch.float64)

        q_target = (config['env']['gamma'] ** steps_to_done
                    * kyoku_rewards).to(torch.float32)
        with torch.autocast(device.type, enabled=enable_amp):
            q_out = dqn(mortal(obs), mask)
            q32 = q_out.float()
            q = q32.gather(1, actions.view(-1, 1)).squeeze(1)
            dqn_loss = 0.5 * torch.nn.functional.mse_loss(q, q_target)
            loss = dqn_loss
            cql_w = (args.selfplay_cql if args.selfplay_cql is not None
                     else config['cql']['min_q_weight'])
            if cql_w > 0:
                q_legal = q32.masked_fill(~mask, 0.0)
                cql = q_legal.logsumexp(-1).mean() - q.mean()
                loss = loss + cql_w * cql
        return loss, q_out, dqn_loss

    try:
        n_sp = 0
        for obs, mask, target in loader:
            # phase 2: take every k-th step from the self-play stream instead
            use_sp = (sp_loader is not None
                      and args.selfplay_frac > 0
                      and ((steps - steps_done) % max(1, int(round(
                          1.0 / args.selfplay_frac)))) == 0)
            if use_sp:
                try:
                    batch = next(sp_loader)
                except StopIteration:
                    sp_loader = iter(DataLoader(
                        sp_ds, batch_size=batch_size, drop_last=True,
                        num_workers=max(1, args.num_workers), pin_memory=True,
                        worker_init_fn=worker_init_fn))
                    batch = next(sp_loader)
                loss, q_out, sp_metric = compute_selfplay_loss(batch)
                metric = float(sp_metric.detach())
                kind = 'sp'
                n_sp += 1
            else:
                loss, q_out, t = compute_loss(obs, mask, target, None)
                metric = float((q_out.argmax(-1) == t.argmax(-1)).float().mean())
                kind = 'kd'

            optimizer.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            if args.grad_clip > 0:
                # the soft target's gradient reaches 1/tau, so an unclipped step
                # can be dominated by a handful of strongly-disagreeing samples
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(
                    list(mortal.parameters()) + list(dqn.parameters()),
                    args.grad_clip)
            scaler.step(optimizer)
            scaler.update()

            with torch.inference_mode():
                run[kind + '_loss'] += float(loss)
                run[kind] += 1
                if kind == 'kd':
                    run['top1'] += metric
            steps += 1

            if (run['kd'] + run['sp']) % 50 == 0:
                p = run
                n_kd = max(1, p['kd'])
                n_spb = max(1, p['sp'])
                writer.add_scalar('distill/loss', p['kd_loss'] / n_kd, steps)
                writer.add_scalar('distill/top1_agree', p['top1'] / n_kd, steps)
                if p['sp']:
                    writer.add_scalar('selfplay/loss', p['sp_loss'] / n_spb,
                                      steps)
                now = time.time()
                # instantaneous rate: using total elapsed here would print a
                # steadily DECLINING number that looks like a slowdown
                rate = (p['kd'] + p['sp']) / max(1e-9, now - last_log)
                last_log = now
                sp_txt = (f'  sp-loss {p["sp_loss"]/n_spb:.4f} ({p["sp"]} sp)'
                          if p['sp'] else '')
                logging.info(
                    f'step {steps:,}  kd-loss {p["kd_loss"]/n_kd:.4f}  '
                    f'top1-agree {100*p["top1"]/n_kd:.2f}%{sp_txt}  '
                    f'{rate:.1f} it/s  elapsed {(now-t0)/60:.1f} min')
                run = {'kd': 0, 'sp': 0, 'kd_loss': 0.0, 'sp_loss': 0.0,
                       'top1': 0.0}

            if steps % args.save_every == 0:
                save()
                if args.snapshot_dir:
                    os.makedirs(args.snapshot_dir, exist_ok=True)
                    snap = path.join(args.snapshot_dir, f'step{steps}.pth')
                    torch.save({
                        'mortal': mortal.state_dict(),
                        'current_dqn': dqn.state_dict(),
                        'aux_net': state.get('aux_net', {}),
                        'optimizer': optimizer.state_dict(),
                        'scheduler': {},
                        'scaler': scaler.state_dict(),
                        'steps': steps,
                        'timestamp': datetime.now().timestamp(),
                        'best_perf': state.get('best_perf', {}),
                        'config': cfg,
                    }, snap)
                    logging.info(f'snapshot -> {snap}')
                gc.collect()

            if args.limit and (steps - steps_done) >= args.limit:
                logging.info(f'stopping after {args.limit} steps (smoke test)')
                break
    except KeyboardInterrupt:
        logging.info('interrupted')
    finally:
        save()
        writer.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
