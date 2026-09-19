#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export harvested hall-of-fame reviews into a COMPACT trainable form.

Storing the observation tensors directly would cost ~16 GB
(595 games x ~216 decisions x 1012 x 34 float32).  Instead we store:

    mortal/distill/logs/<id>_s<seat>.json.gz    the mjai log  (~4 KB each)
    mortal/distill/targets.pt                   {key: {target, valid}}

`obs` is deterministic given the log, and libriichi's loader regenerates it
quickly in parallel, so there is no reason to persist it.  Total footprint is a
few tens of MB.

ALIGNMENT
---------
The replay emits more rows than the report (extra kan-tile-selection rows).  We
align with difflib -- validated at 100% over 2135 decisions -- and store

    target : (n_replay_rows, 46)  Akino Hana's pi, zero on unaligned rows
    valid  : (n_replay_rows,)     True only where the report covered the row

so the loss only learns from rows that actually have a target.
"""
from __future__ import annotations

import argparse
import difflib
import gzip
import json
import os
import pathlib
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
MORTAL = ROOT / "mortal"
OUT_DEFAULT = MORTAL / "distill"

ACTION_SPACE = 46
HONORS = ["E", "S", "W", "N", "P", "F", "C"]


def tile_index(t: str) -> int:
    t = t.replace("r", "")
    if len(t) == 2 and t[0].isdigit():
        return {"m": 0, "p": 9, "s": 18}[t[1]] + int(t[0]) - 1
    return 27 + HONORS.index(t)


def action_index(a: dict) -> int | None:
    """mjai action -> Mortal 46-dim index (mirrors libriichi gameplay.rs)."""
    t = a.get("type")
    if t == "dahai":
        pai = a.get("pai")
        if not pai:
            return None
        i = tile_index(pai)
        return {4: 34, 13: 35, 22: 36}[i] if pai.endswith("r") else i
    if t == "reach":
        return 37
    if t == "chi":
        cons, pai = a.get("consumed") or [], a.get("pai")
        if len(cons) != 2 or not pai:
            return None
        lo, hi = sorted(tile_index(x) for x in cons)
        ti = tile_index(pai)
        return 38 if ti < lo else (39 if ti < hi else 40)
    if t == "pon":
        return 41
    if t in ("kan", "ankan", "kakan", "daiminkan"):
        return 42
    if t == "hora":
        return 43
    if t == "ryukyoku":
        return 44
    if t == "none":
        return 45
    return None


def align(rep_idx, actions):
    a = ["?" if x is None else str(x) for x in rep_idx]
    b = [str(int(x)) for x in actions]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    pairs = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ("equal", "replace"):
            for k in range(min(i2 - i1, j2 - j1)):
                pairs.append((i1 + k, j1 + k))
    return pairs


def main() -> int:
    import numpy as np
    import torch

    ap = argparse.ArgumentParser()
    ap.add_argument("--hof", type=Path, default=HERE / "out" / "hof")
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    args.hof = args.hof.resolve()
    args.out = args.out.resolve()
    log_dir = args.out / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(f for f in args.hof.glob("*.json") if not f.name.startswith("_"))
    if args.limit:
        files = files[:args.limit]
    print(f"{len(files)} review(s) -> {args.out}")
    print()

    prev = os.getcwd()
    os.chdir(MORTAL)
    sys.path.insert(0, str(MORTAL))
    from libriichi.dataset import GameplayLoader
    loader = GameplayLoader(version=4, player_names=[], excludes=[], augmented=False)

    targets = {}
    used = skipped = 0
    total_rows = total_valid = 0
    reasons = {}

    for i, f in enumerate(files, 1):
        obj = json.loads(f.read_text(encoding="utf-8"))
        log = obj.get("mjai_log")
        pid = obj.get("player_id")
        hof = obj.get("_hof") or {}
        cid = hof.get("canonicalId") or f.stem
        seat = hof.get("seat", pid)
        if not log or pid is None:
            skipped += 1
            reasons["no log/player_id"] = reasons.get("no log/player_id", 0) + 1
            continue
        events = ([json.loads(x) for x in log.splitlines() if x.strip()]
                  if isinstance(log, str) else log)

        gz = log_dir / f"{cid}_s{seat}.json.gz"
        with gzip.open(gz, "wt", encoding="utf-8", newline="\n") as fh:
            for ev in events:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")

        data = loader.load_gz_log_files([str(gz)])
        games = [g for grp in data for g in grp]
        mine = next((g for g in games if g.take_player_id() == pid), None)
        if mine is None:
            skipped += 1
            reasons["player not in replay"] = reasons.get("player not in replay", 0) + 1
            continue
        actions = mine.take_actions()

        entries = [e for k in (obj.get("review", {}).get("kyokus") or [])
                   for e in (k.get("entries") or [])]
        rep_idx = [action_index(e.get("actual") or {}) for e in entries]
        pairs = align(rep_idx, actions)
        if len(pairs) != len(entries):
            skipped += 1
            reasons["alignment incomplete"] = reasons.get("alignment incomplete", 0) + 1
            continue
        agree = sum(1 for a_, b_ in pairs
                    if rep_idx[a_] is None or rep_idx[a_] == int(actions[b_]))
        if agree / len(pairs) < 0.99:
            skipped += 1
            reasons["alignment agreement"] = reasons.get("alignment agreement", 0) + 1
            continue

        n = len(actions)
        tgt = np.zeros((n, ACTION_SPACE), dtype=np.float32)
        val = np.zeros((n,), dtype=bool)
        for a_, b_ in pairs:
            e = entries[a_]
            tot = 0.0
            row = np.zeros(ACTION_SPACE, dtype=np.float32)
            for d in (e.get("details") or []):
                p = float(d.get("prob") or 0.0)
                tot += p
                idx = action_index(d.get("action") or {})
                if idx is not None:
                    row[idx] += p
            if tot <= 0 or row.sum() <= 0:
                continue
            tgt[b_] = row / row.sum()
            val[b_] = True

        targets[f"{cid}_s{seat}"] = {"target": torch.from_numpy(tgt),
                                     "valid": torch.from_numpy(val)}
        used += 1
        total_rows += n
        total_valid += int(val.sum())
        if i % 50 == 0:
            print(f"  [{i}/{len(files)}] used={used} skipped={skipped} "
                  f"rows={total_rows:,}")

    os.chdir(prev)

    args.out.mkdir(parents=True, exist_ok=True)
    torch.save({"games": targets,
                "meta": {"games": used, "skipped": skipped,
                         "rows": total_rows, "valid_rows": total_valid}},
               args.out / "targets.pt")

    print()
    print(f"=== exported ===")
    print(f"  games        : {used} (skipped {skipped})")
    print(f"  replay rows  : {total_rows:,}")
    print(f"  valid targets: {total_valid:,} "
          f"({100.0*total_valid/max(1,total_rows):.1f}% of rows)")
    print(f"  logs         : {log_dir}")
    print(f"  targets      : {args.out / 'targets.pt'}")
    if reasons:
        print("  skip reasons:")
        for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {v:4}x {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
