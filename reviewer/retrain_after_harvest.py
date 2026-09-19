#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge the free-harvested reviews into the distillation set and retrain.

Pipeline (one command once the harvest reaches the desired size):

    1. export_distill.py  hof_free                     -> staging targets.pt
    2. merge staging into mortal/distill/              (logs + targets dict)
    3. distill.py         full retrain (soft tau=1.0 + hard, 1 epoch)
    4. eval_distill.py    train/val comparison

The train/val split is deterministic, so the new games change the val set as
well -- merge first, THEN retrain, so both sides grow together.

    python reviewer\\retrain_after_harvest.py [--min-new 50] [--no-train]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
HOF_FREE = ROOT / "reviewer" / "out" / "hof_free"
STAGING = ROOT / "reviewer" / "out" / "_free_staging"
DISTILL = ROOT / "mortal" / "distill"


def count_free() -> int:
    try:
        return len([f for f in HOF_FREE.glob("*.json") if f.name != "_index.json"])
    except Exception:
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-new", type=int, default=50,
                    help="minimum free-harvest size before retraining")
    ap.add_argument("--no-train", action="store_true",
                    help="merge only, skip the training run")
    ap.add_argument("--state-file", default=str(
        ROOT / "backups" / "phase2_selfplay_step325000.pth"),
        help="checkpoint to resume from")
    ap.add_argument("--out", default=str(ROOT / "reviewer" / "out" / "_retrained.pth"))
    args = ap.parse_args()

    n = count_free()
    print(f"free-harvest reviews on disk: {n}")
    if n < args.min_new:
        print(f"below --min-new {args.min_new}; nothing to do")
        return 0

    # ---- 1. export ------------------------------------------------------ #
    print("\n[1/4] exporting hof_free -> staging")
    r = subprocess.run([str(PY), str(ROOT / "reviewer" / "export_distill.py"),
                        "--hof", str(HOF_FREE), "--out", str(STAGING)],
                       capture_output=True, text=True, encoding="utf-8")
    print(r.stdout[-400:])
    if r.returncode != 0:
        print("export failed:", r.stderr[-500:])
        return 1

    # ---- 2. merge -------------------------------------------------------- #
    print("[2/4] merging staging into mortal/distill")
    src_logs = sorted((STAGING / "logs").glob("*.json.gz"))
    dst_logs = DISTILL / "logs"
    dst_logs.mkdir(parents=True, exist_ok=True)
    added = 0
    for f in src_logs:
        if not (dst_logs / f.name).exists():
            shutil.copy2(f, dst_logs / f.name)
            added += 1

    import torch
    new_t = torch.load(STAGING / "targets.pt", weights_only=False)
    new_games = new_t.get("games", {})
    dst_t = DISTILL / "targets.pt"
    if dst_t.is_file():
        old = torch.load(dst_t, weights_only=False)
        games = old.get("games", {})
        meta = old.get("meta", {})
    else:
        games, meta = {}, {}
    merged = 0
    for k, v in new_games.items():
        if k not in games:
            games[k] = v
            merged += 1
    meta["games"] = len(games)
    meta["valid_rows"] = int(sum(v["valid"].sum().item()
                                 for v in games.values()))
    torch.save({"games": games, "meta": meta}, dst_t)
    print(f"   logs added: {added}   targets merged: {merged}   "
          f"total games now: {meta['games']}   valid rows: "
          f"{meta['valid_rows']:,}")
    (STAGING / "targets.pt").unlink(missing_ok=True)

    if args.no_train:
        print("[3-4] skipped (--no-train)")
        return 0

    # ---- 3. retrain ------------------------------------------------------ #
    print("[3/4] retraining (soft tau=1.0 + hard, 1 epoch)")
    cmd = [str(PY), str(ROOT / "mortal" / "distill.py"),
           "--tau", "1.0", "--w-hard", "1.0", "--w-distill", "1.0",
           "--lr", "1e-5", "--state-file", args.state_file,
           "--split", "all", "--epochs", "1",
           "--save-every", "500",
           "--num-workers", "2", "--out", args.out]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    lines = [l for l in (r.stdout or "").splitlines() if "kd-loss" in l]
    for l in lines[-2:]:
        print("   ", l.split("INFO", 1)[-1].strip())
    if r.returncode != 0:
        print("train failed:", (r.stderr or "")[-600:])
        return 1

    # ---- 4. evaluate ------------------------------------------------------ #
    print("[4/4] evaluating train vs val vs baseline")
    eval_cmd = [str(PY), str(ROOT / "mortal" / "eval_distill.py"),
                str(ROOT / "backups" / "before_distill_321275.pth"),
                args.out, "--num-workers", "2"]
    r2 = subprocess.run(eval_cmd, capture_output=True, text=True,
                        encoding="utf-8")
    print(r2.stdout[-1200:])
    return 0


if __name__ == "__main__":
    sys.exit(main())