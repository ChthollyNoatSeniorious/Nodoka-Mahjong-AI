#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Automated long-run harvest at the measured sustainable rate.

Measured: with a 45s gap, the server grants ~7 runs per window and then replies
429 with retry-after ~3200s.  This runs repeated batches of that size, sleeping
the full cooldown between batches, and stops on any cap/suspension signal.

    python reviewer\\auto_harvest.py --max-games 300 --batch 7 --delay 45

Safety:
  * a batch never exceeds --batch (default 7)
  * after a 429 it sleeps retry-after + 300s before the next batch
  * if retry-after ever exceeds 7200s it stops (cooldown escalation)
  * on HOF_DAILY_RUNS_EXCEEDED / SUSPENDED it stops and reports the number
  * Ctrl-C between batches is clean; the _index.json is authoritative
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
EXP = HERE / "rate_experiment.py"
INDEX = ROOT / "reviewer" / "out" / "hof_free" / "_index.json"


def count_indexed() -> int:
    try:
        return len(json.loads(INDEX.read_text(encoding="utf-8")))
    except Exception:
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-games", type=int, default=300)
    ap.add_argument("--batch", type=int, default=7)
    ap.add_argument("--delay", type=float, default=45.0)
    ap.add_argument("--cooldown-pad", type=float, default=300.0,
                    help="extra seconds on top of retry-after")
    ap.add_argument("--max-cooldown", type=float, default=7200.0,
                    help="stop if retry-after exceeds this")
    ap.add_argument("--log-dir", default=str(ROOT / "reviewer" / "out"))
    args = ap.parse_args()

    if not os.environ.get("BIGCOACH_COOKIE"):
        print("set BIGCOACH_COOKIE first", file=sys.stderr)
        return 2

    log_dir = pathlib.Path(args.log_dir)
    total_before = count_indexed()
    start = time.time()
    print(f"auto_harvest: batch={args.batch} delay={args.delay}s "
          f"max_games={args.max_games}  indexed now={total_before}")

    batch_no = 0
    while True:
        have = count_indexed() - total_before
        if have >= args.max_games:
            print(f"target reached ({have} new). done.")
            break
        batch_no += 1
        logf = log_dir / f"_auto_batch{batch_no:03d}.log"
        cmd = [str(PY), str(EXP), "--limit", str(args.batch),
               "--delay", str(args.delay), "--stop-on-429",
               "--player", "☆孫燕姿☆"]
        print(f"\n=== batch {batch_no}: {cmd[3:]} "
              f"(elapsed {(time.time()-start)/3600:.2f}h, "
              f"+{have} so far) ===", flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        logf.write_text(r.stdout + r.stderr, encoding="utf-8")

        # parse: how many new runs, any rate limit, any cap signal
        new_runs = re.findall(r"new runs \(free\)\s*:\s*(\d+)", r.stdout)
        ra_hits = re.findall(r"retry-after=(\d+)s", r.stdout)
        capped = "CAP REACHED" in r.stdout or "SUSPENDED" in r.stdout
        tail = [l for l in r.stdout.splitlines()
                if "EXPERIMENT SUMMARY" in l or "new runs" in l
                or "stop reason" in l or "CAP" in l or "SUSPEND" in l]
        for t in tail[-4:]:
            print("   ", t)

        if capped:
            print("cap/suspension signal seen; stopping (check the log)")
            break
        if not ra_hits:
            if int(new_runs[0]) if new_runs else 0 <= 0:
                print("batch produced nothing and no rate limit; stopping")
                break
            # finished the batch without hitting the limit
            print("   no 429 in this batch "
                  f"(indexed {count_indexed()} total)")
            time.sleep(120)
            continue

        wait = max(float(ra_hits[-1]), 60.0)
        if wait > args.max_cooldown:
            print(f"cooldown {wait:.0f}s > max {args.max_cooldown:.0f}s; "
                  f"stopping (escalation guard)")
            break
        wait += args.cooldown_pad
        print(f"   sleeping {wait/60:.1f} min before next batch "
              f"({time.strftime('%H:%M')})")
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            print("interrupted between batches")
            break

    print(f"\nfinal: +{count_indexed()-total_before} games "
          f"in {(time.time()-start)/3600:.1f}h "
          f"(total indexed {count_indexed()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())