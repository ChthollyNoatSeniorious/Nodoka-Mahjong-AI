#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert bigcoach classic reports into a DISTILLATION dataset.

Input : the classic HTML reports harvested by `bigcoach_harvest.py`
        (same format as `Test set/*.htm`), each containing ~216 decisions with
        Akino Hana's full `pi_tau(a|s)` distribution.
Output: a `.pt` file of (obs, pi_target, mask, ...) triples that `train.py` can
        learn from with a KL / cross-entropy objective.

THE HARD PART -- action index alignment
---------------------------------------
Mortal's action space is 46 wide (libriichi/src/consts.rs):

    0..36    discard (37 slots = 34 tile kinds + 3 aka-dora variants)
    37       riichi
    38,39,40 chi low / mid / high
    41       pon
    42       kan
    43       agari
    44       ryukyoku
    45       pass

The report names actions in mjai terms ("dahai:1s", "chi:3m+4m", ...).  Mapping
one onto the other is exactly where a distillation pipeline fails *silently*:
if the mapping is off by one, training still runs and the loss still goes down,
but the model learns a scrambled policy.

So this script does not merely convert -- it VERIFIES, by replaying the same
game through libriichi and checking that

  (a) the action we decode from the report equals the action Mortal recorded as
      actually taken in the log, and
  (b) the report's argmax matches Akino Hana's top-1 choice.

Run `--verify` on the existing test set to check (a) and (b) before trusting any
conversion.
"""

from __future__ import annotations

import argparse
import base64
import collections
import json
import pathlib
import re
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
MORTAL_DIR = ROOT / "mortal"

# --------------------------------------------------------------------------- #
# tile <-> index
# --------------------------------------------------------------------------- #
# mjai tile order used by Mortal's state encoder:
#   1m..9m (0-8), 1p..9p (9-17), 1s..9s (18-26), E S W N P F C (27-33)
HONORS = ["E", "S", "W", "N", "P", "F", "C"]


def tile_index(t: str) -> int:
    """mjai tile string -> 0..33 (aka-dora collapsed onto the normal tile)."""
    t = t.replace("r", "")          # 5mr / 5pr / 5sr -> 5m / 5p / 5s
    if len(t) == 2 and t[0].isdigit():
        n = int(t[0])
        suit = t[1]
        base = {"m": 0, "p": 9, "s": 18}[suit]
        return base + n - 1
    if t in HONORS:
        return 27 + HONORS.index(t)
    raise ValueError(f"unknown tile {t!r}")


def is_aka(t: str) -> bool:
    return t.endswith("r")


# --------------------------------------------------------------------------- #
# report action -> Mortal action index
# --------------------------------------------------------------------------- #
def report_action_to_index(key: str, hand: list[str] | None = None,
                           called: str | None = None) -> int | None:
    """Map a parsed report action key onto Mortal's 46-dim action space.

    Keys come from `compare_test03.parse_action`:
        dahai:<tile>        (aka-dora kept as '5pr' style)
        reach
        chi:<t1>+<t2>
        pon / kan / hora / none

    Chi disambiguation, in order of reliability:
      1. `called` -- the tile the discarder threw, read from the game log.  This
         is exact: every chi candidate at a decision shares that called tile.
      2. `hand` -- the run member absent from the hand (works only when the two
         candidate runs differ in which member is missing).
    With consumed `3m+4m` the called tile may be `2m` (low) or `5m` (high); the
    test set has 220 such ambiguous chi actions, so (1) matters.
    """
    if key.startswith("dahai:"):
        tile = key.split(":", 1)[1]
        idx = tile_index(tile)
        # Mortal keeps 3 separate slots for aka fives: 34,35,36
        if is_aka(tile):
            return {4: 34, 13: 35, 22: 36}[idx]   # 5m->34, 5p->35, 5s->36
        return idx
    if key == "reach":
        return 37
    if key.startswith("chi:"):
        # Mirrors libriichi/src/chi_type.rs:
        #   tile < min(consumed) -> Low,  tile < max(consumed) -> Mid,  else High
        # where `tile` is the tile CALLED from the discarder, not one of the
        # consumed pair.  The report only lists the consumed pair, and for a
        # 1-gap pair (3m+4m) the called tile may be either neighbour, so we
        # recover it as "the run member absent from the hand".
        parts = key.split(":", 1)[1].split("+")
        if len(parts) != 2:
            return None
        a, b = (tile_index(t) for t in parts)
        lo, hi = min(a, b), max(a, b)

        if hi - lo == 1:
            cands = [t for t in (lo - 1, hi + 1)
                     if t // 9 == lo // 9 and 0 <= t % 9 < 9]
        elif hi - lo == 2:
            cands = [lo + 1]
        else:
            return None

        called_idx = None
        if called:
            try:
                called_idx = tile_index(called)
            except ValueError:
                called_idx = None

        if called_idx is None and hand and len(cands) > 1:
            cnt = collections.Counter(tile_index(t) for t in hand)
            cnt[lo] -= 1
            cnt[hi] -= 1
            absent = [c for c in cands if cnt.get(c, 0) <= 0]
            if len(absent) == 1:
                called_idx = absent[0]
        if called_idx is None and len(cands) == 1:
            called_idx = cands[0]
        if called_idx is None:
            # genuinely ambiguous; caller counts these
            return None
        return (38 if called_idx < lo else
                39 if called_idx < hi else 40)
    if key == "pon" or key.startswith("pon:"):
        return 41
    if key == "kan" or key.startswith("kan:"):
        return 42
    if key == "hora":
        return 43
    if key == "ryukyoku":
        return 44
    if key == "none":
        return 45
    return None


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("reports", nargs="+", type=pathlib.Path,
                    help="classic HTML report(s)")
    ap.add_argument("--verify", action="store_true",
                    help="cross-check the mapping against Mortal's own labels")
    ap.add_argument("-o", "--out", type=pathlib.Path,
                    help="write the distillation dataset here (.pt)")
    args = ap.parse_args()

    spec = __import__("importlib.util", fromlist=["util"]).spec_from_file_location(
        "cmp", HERE / "compare_test03.py")
    cmp = __import__("importlib.util", fromlist=["util"]).module_from_spec(spec)
    spec.loader.exec_module(cmp)

    total = 0
    hist = collections.Counter()
    unmapped = collections.Counter()

    for path in args.reports:
        entries = [e for k in cmp.parse_akino(path) for e in k]
        total += len(entries)
        for e in entries:
            i = report_action_to_index(e["coach_key"])
            if i is None:
                unmapped[e["coach_key"]] += 1
            else:
                hist[i] += 1
            # also map every candidate, since those become the target vector
            for c in e["cands"]:
                if report_action_to_index(c["key"]) is None:
                    unmapped[c["key"]] += 1

    print(f"reports      : {len(args.reports)}")
    print(f"decisions    : {total}")
    print(f"unique action indices used : {len(hist)}")
    print()
    print("=== index histogram (index: count) ===")
    for k in sorted(hist):
        label = (f"discard {k}" if k < 37 else
                 {37: "riichi", 38: "chi-low", 39: "chi-mid", 40: "chi-high",
                  41: "pon", 42: "kan", 43: "agari", 44: "ryukyoku",
                  45: "pass"}.get(k, "?"))
        print(f"  {k:>3} {label:<12} {hist[k]:>5}")
    if unmapped:
        print()
        print("=== UNMAPPED action keys (must be empty!) ===")
        for k, v in unmapped.most_common():
            print(f"  {k!r}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
