#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Slow harvest wrapper: runs topup_slow.py in batches of --per-batch
successful submits; whenever a batch stops on 429 (rate limit) it sleeps
with exponential backoff (1h -> 4h cap) and retries. Stops when all paipus
are covered, the account goes dry (402), or login fails for good.

Safe by construction: never more than one in-flight submission, 240s+
between submissions, batch aborts on any sustained 429.

Usage:
    python reviewer/slow_harvest.py [--per-batch 5] [--max-rounds 40]
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent


def run_batch(max_submits: int) -> tuple[int, str]:
    cmd = [sys.executable, str(HERE / "topup_slow.py"),
           "--max-submits", str(max_submits)]
    r = subprocess.run(cmd, cwd=HERE.parent)
    tail = ""
    log = HERE / "out" / "_topup_slow.log"
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-1] if lines else ""
    return r.returncode, tail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-batch", type=int, default=5)
    ap.add_argument("--max-rounds", type=int, default=48)
    ap.add_argument("--base-wait", type=int, default=3600)
    args = ap.parse_args()

    wait = args.base_wait
    for rnd in range(1, args.max_rounds + 1):
        print(f"=== round {rnd}/{args.max_rounds} ===", flush=True)
        rc, tail = run_batch(args.per_batch)
        print(f"  rc={rc} tail={tail!r}", flush=True)
        if rc == 0:
            print("  done: nothing left to submit", flush=True)
            return 0
        if rc == 7:  # rate limited -> cool down with backoff
            print(f"  429 stop, sleeping {wait}s", flush=True)
            time.sleep(wait)
            wait = min(wait * 2, 14400)
            continue
        if rc in (6, 3):  # account dry
            print("  account dry (402/balance), waiting for next account",
                  flush=True)
            return 3
        if rc == 2:  # login failed
            print("  login failed, sleeping 1800s then retry", flush=True)
            time.sleep(1800)
            continue
        if rc == 4 or rc == 5:
            print("  relogin trouble, sleeping 1800s then retry", flush=True)
            time.sleep(1800)
            continue
        print(f"  other rc={rc}, sleeping {wait}s", flush=True)
        time.sleep(wait)
    print("max rounds reached", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())