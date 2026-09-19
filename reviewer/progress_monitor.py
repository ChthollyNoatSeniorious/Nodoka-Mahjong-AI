#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hourly progress monitor for the auto harvest.

Every 3600s it appends one snapshot line to reviewer/out/_progress.log:

    HH:MM  batch=N  games=TOTAL  +NEW=delta  eta≈X.Xd  status

It derives state from the harvest's own artifacts (index + log) and stops when
the harvest log has not grown for >2 hours (harvest died or finished).
"""
from __future__ import annotations

import pathlib
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOF = ROOT / "reviewer" / "out" / "hof_free"
HLOG = ROOT / "reviewer" / "out" / "_adaptive.log"
PLOG = ROOT / "reviewer" / "out" / "_progress.log"

TARGET = 300
START_TARGET_INDEX = 0  # filled on first tick from the index


def games_on_disk():
    try:
        return len(list(HOF.glob("*.json"))) - 1  # exclude _index.json
    except Exception:
        return 0


def digest():
    n = games_on_disk()
    batch = "?"
    status = "harvest log missing"
    if HLOG.is_file():
        lines = HLOG.read_text(encoding="utf-8", errors="replace").splitlines()
        for l in reversed(lines):
            if "=== batch" in l:
                batch = l.split("batch")[1].split(":")[0].strip()
                break
        tail = "\n".join(lines[-6:])
        if "target reached" in tail:
            status = "DONE (target reached)"
        elif "DAILY_QUOTA" in tail:
            status = "STOPPED (daily quota)"
        elif "cap/suspension" in tail or "CAP" in tail:
            status = "STOPPED (cap/suspension)"
        elif "escalation guard" in tail:
            status = "STOPPED (cooldown escalation)"
        elif "produced nothing" in tail:
            status = "STOPPED (no progress)"
        elif "interrupted" in tail:
            status = "STOPPED (interrupted)"
        else:
            status = "harvesting"
    return n, batch, status


def main() -> int:
    global START_TARGET_INDEX
    fmt = "%Y-%m-%d %H:%M:%S"
    start = time.time()
    last_size = -1
    try:
        while True:
            n, batch, status = digest()
            if "DONE" in status or "STOPPED" in status:
                line = (f"[{time.strftime(fmt)}] batch={batch} games={n} "
                        f"delta={n-START_TARGET_INDEX} status={status} "
                        f"(harvest finished, monitor exits)")
                print(line, flush=True)
                with PLOG.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
                return 0
            sz = HLOG.stat().st_size if HLOG.is_file() else 0
            if last_size >= 0 and sz == last_size and time.time() - start > 7200:
                line = (f"[{time.strftime(fmt)}] batch={batch} games={n} "
                        f"status=HARVEST_STALE ({time.time()-start/3600:.1f}h "
                        f"no log growth) -- monitor exits")
                print(line, flush=True)
                with PLOG.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
                return 0
            last_size = sz
            eta_d = max(0.0, (TARGET - n) / 150.0)  # ~150 games/day
            line = (f"[{time.strftime(fmt)}] batch={batch} games={n} "
                    f"delta={n-START_TARGET_INDEX} eta≈{eta_d:.1f}d "
                    f"status={status}")
            print(line, flush=True)
            with PLOG.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            time.sleep(3600)
    except KeyboardInterrupt:
        print("monitor interrupted")
        return 0


if __name__ == "__main__":
    sys.exit(main())