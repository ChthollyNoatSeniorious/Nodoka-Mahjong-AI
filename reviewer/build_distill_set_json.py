#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a distillation dataset from HARVESTED hall-of-fame review JSON.

Input : reviewer/out/hof/*.json   (free RIGEL 1.4 analyses, see hof_harvest.py)
Output: a .pt with (obs, target, mask, label) ready for a KL distillation loss.

Each sample teaches the model Akino Hana's FULL action distribution, not just its
top choice -- which is what lets the student reproduce the second and third
choices too, and is the only way to match it on near-tie decisions.

Pipeline per game
-----------------
  1. mjai_log  -> libriichi replay -> obs (1012,34), mask (46,), label (46,)
  2. review.kyokus[].entries[] -> target vector (46,) from details[].prob
  3. align the two with difflib (validated at 100% over 2135 decisions)

Why the JSON route is better than the HTML route
------------------------------------------------
`details[].action` is a full mjai action dict, so a chi carries BOTH the called
tile (`pai`) and the two hand tiles (`consumed`).  Low/mid/high can therefore be
computed exactly, with no ambiguity and no dropped samples:

    index = 38 if called < min(consumed) else 39 if called < max(consumed) else 40
    (libriichi/src/chi_type.rs)

USAGE
-----
    python reviewer\\build_distill_set_json.py --hof reviewer\\out\\hof -o reviewer\\out\\distill_hof.pt
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
TMP = HERE / "out" / "_replay"

ACTION_SPACE = 46
HONORS = ["E", "S", "W", "N", "P", "F", "C"]


def tile_index(t: str) -> int:
    """mjai tile -> 0..33 (aka-dora collapsed)."""
    t = t.replace("r", "")
    if len(t) == 2 and t[0].isdigit():
        return {"m": 0, "p": 9, "s": 18}[t[1]] + int(t[0]) - 1
    return 27 + HONORS.index(t)


def action_index(a: dict) -> int | None:
    """mjai action dict -> Mortal's 46-dim action index.

    Mirrors libriichi/src/dataset/gameplay.rs and chi_type.rs.
    """
    t = a.get("type")
    if t == "dahai":
        pai = a.get("pai")
        if not pai:
            return None
        i = tile_index(pai)
        if pai.endswith("r"):
            return {4: 34, 13: 35, 22: 36}[i]      # aka 5m / 5p / 5s
        return i
    if t == "reach":
        return 37
    if t == "chi":
        cons = a.get("consumed") or []
        pai = a.get("pai")
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


def alignment_pairs(rep_idx: list[int | None], actions) -> list[tuple[int, int]]:
    """Pair report rows with replay rows, tolerating extra kan-select rows."""
    a = ["?" if x is None else str(x) for x in rep_idx]
    b = [str(int(x)) for x in actions]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    pairs = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ("equal", "replace"):
            for k in range(min(i2 - i1, j2 - j1)):
                pairs.append((i1 + k, j1 + k))
    return pairs


def process(path: pathlib.Path, verbose=False):
    import numpy as np

    obj = json.loads(path.read_text(encoding="utf-8"))
    log = obj.get("mjai_log")
    if not log:
        return None, "no mjai_log"
    events = ([json.loads(x) for x in log.splitlines() if x.strip()]
              if isinstance(log, str) else log)
    player_id = obj.get("player_id")
    if player_id is None:
        return None, "no player_id"

    TMP.mkdir(parents=True, exist_ok=True)
    gz = TMP / f"{path.stem}.json.gz"
    with gzip.open(gz, "wt", encoding="utf-8", newline="\n") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")

    prev = os.getcwd()
    os.chdir(MORTAL)
    sys.path.insert(0, str(MORTAL))
    try:
        from libriichi.dataset import GameplayLoader
        loader = GameplayLoader(version=4, player_names=[], excludes=[],
                                augmented=False)
        data = loader.load_gz_log_files([str(gz)])
        games = [g for grp in data for g in grp]
        mine = next((g for g in games if g.take_player_id() == player_id), None)
        if mine is None:
            return None, "player not found in replay"
        obs = mine.take_obs()
        actions = mine.take_actions()
        masks = mine.take_masks()
    except Exception as exc:
        return None, f"replay failed: {exc}"
    finally:
        os.chdir(prev)

    entries = [e for k in (obj.get("review", {}).get("kyokus") or [])
               for e in (k.get("entries") or [])]
    if not entries:
        return None, "no entries"

    # order actions in the same sequence as the replay expects them: for a human
    # game the replay label IS the human action, so align on that.
    rep_idx = []
    for e in entries:
        rep_idx.append(action_index(e.get("actual") or {}))
    pairs = alignment_pairs(rep_idx, actions)
    if len(pairs) != len(entries):
        return None, f"alignment incomplete {len(pairs)}/{len(entries)}"
    agree = sum(1 for i, j in pairs
                if rep_idx[i] is None or rep_idx[i] == int(actions[j]))
    if agree / len(pairs) < 0.99:
        return None, f"alignment agreement {agree}/{len(pairs)}"

    O, T, M, L = [], [], [], []
    dropped = 0
    for i, j in pairs:
        e = entries[i]
        t = np.zeros(ACTION_SPACE, dtype=np.float32)
        total = 0.0
        for d in (e.get("details") or []):
            p = float(d.get("prob") or 0.0)
            total += p
            idx = action_index(d.get("action") or {})
            if idx is None:
                continue
            t[idx] += p
        if total <= 0:
            dropped += 1
            continue
        if t.sum() <= 0:
            dropped += 1
            continue
        t /= t.sum()
        O.append(np.asarray(obs[j], dtype=np.float32))
        T.append(t)
        M.append(np.asarray(masks[j], dtype=bool))
        L.append(int(actions[j]))

    if not O:
        return None, "no usable samples"
    return (np.stack(O), np.stack(T), np.stack(M),
            np.asarray(L, dtype=np.int64),
            {"rows": len(O), "dropped": dropped}), None


def main() -> int:
    import numpy as np
    import torch

    ap = argparse.ArgumentParser()
    ap.add_argument("--hof", type=Path, default=HERE / "out" / "hof")
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    args.hof = args.hof.resolve()
    args.out = args.out.resolve()
    files = sorted(f for f in args.hof.glob("*.json") if not f.name.startswith("_"))
    print(f"{len(files)} harvested review(s) in {args.hof}")
    print()

    O, T, M, L = [], [], [], []
    used = skipped = 0
    reasons = {}
    for i, f in enumerate(files, 1):
        r, err = process(f, verbose=args.verbose)
        if r is None:
            skipped += 1
            reasons[err] = reasons.get(err, 0) + 1
            if args.verbose:
                print(f"  skip {f.name[:44]}: {err}")
            continue
        o, t, m, l, st = r
        O.append(o); T.append(t); M.append(m); L.append(l)
        used += 1
        if i % 25 == 0:
            print(f"  [{i}/{len(files)}] used={used} skipped={skipped}")

    if not O:
        print("\nno usable games")
        for k, v in reasons.items():
            print(f"  {v}x {k}")
        return 1

    obs = torch.from_numpy(np.concatenate(O))
    target = torch.from_numpy(np.concatenate(T))
    mask = torch.from_numpy(np.concatenate(M))
    label = torch.from_numpy(np.concatenate(L))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"obs": obs, "target": target, "mask": mask, "label": label,
                "meta": {"games": used, "skipped": skipped,
                         "rows": int(obs.shape[0]), "source": "hall_of_fame"}},
               args.out)

    print()
    print(f"=== saved {args.out} ===")
    print(f"  games          : {used} (skipped {skipped})")
    print(f"  samples        : {obs.shape[0]:,}")
    print(f"  obs            : {tuple(obs.shape)}")
    print(f"  target         : {tuple(target.shape)}  sum={target.sum(-1).mean():.4f}")
    print(f"  mask           : {tuple(mask.shape)}  legal/sample={mask.sum(-1).float().mean():.2f}")

    # correctness checks
    in_mask = mask.gather(1, target.argmax(-1, keepdim=True)).squeeze(1)
    print(f"  argmax(target) legal : {in_mask.float().mean()*100:.2f}%")
    covered = (target * mask.float()).sum(-1)
    print(f"  target mass on legal : {covered.mean()*100:.2f}%  (should be ~100%)")
    top1 = target.argmax(-1)
    print(f"  argmax==label        : {(top1 == label).float().mean()*100:.1f}% "
          f"(target is Akino Hana, label the human)")
    if reasons:
        print()
        print("  skip reasons:")
        for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {v:4}x {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
