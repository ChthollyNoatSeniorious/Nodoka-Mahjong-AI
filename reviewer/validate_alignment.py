#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate the report<->replay alignment across ALL test games.

On test03 the pairing came out at 100% (216/216) using difflib sequence
alignment, with 6 extra replay entries that are kan-select rows (mask.sum()==1).

Before building a distillation set for 1765 games we must know this holds
generally -- a game that aligns at, say, 70% would silently corrupt its targets.

For each test game we:
  1. take the mjai_log embedded in our own mjai-reviewer JSON report
  2. replay it through libriichi exactly as train.py does
  3. align the report's decisions with the replay entries
  4. report agreement, and the nature of any unmatched replay entries

Any game scoring below a threshold is flagged and should be excluded.

Usage (repo root):  python reviewer\\validate_alignment.py
"""
from __future__ import annotations

import difflib
import gzip
import importlib.util
import json
import os
import pathlib
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
MORTAL = ROOT / "mortal"
JSON_DIR = HERE / "out" / "testset"
TMP = HERE / "out" / "replay_probe"
TMP.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location("cmp", HERE / "compare_test03.py")
cmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp)
spec2 = importlib.util.spec_from_file_location("dist", HERE / "bigcoach_distill.py")
dist = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(dist)

os.chdir(MORTAL)
sys.path.insert(0, str(MORTAL))
from libriichi.dataset import GameplayLoader


def replay(mjai_events, tag):
    gz = TMP / f"{tag}_replay.json.gz"
    with gzip.open(gz, "wt", encoding="utf-8", newline="\n") as fh:
        for ev in mjai_events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    loader = GameplayLoader(version=4, player_names=[], excludes=[], augmented=False)
    data = loader.load_gz_log_files([str(gz)])
    return [g for grp in data for g in grp]


def main() -> int:
    results = []
    for n in range(1, 11):
        tag = f"test{n:02d}"
        jf = JSON_DIR / f"{tag}_finetune_step321275.json"
        htm = next(cmp.TESTSET.glob(f"{tag}_*.htm"))
        if not jf.is_file():
            print(f"{tag}: no JSON report, skipped")
            continue

        rep = json.loads(jf.read_text(encoding="utf-8"))
        player_id = rep.get("player_id", 0)
        log = rep.get("mjai_log")
        if not log:
            print(f"{tag}: no mjai_log embedded, skipped")
            continue
        events = ([json.loads(x) for x in log.splitlines() if x.strip()]
                  if isinstance(log, str) else log)

        games = replay(events, tag)
        mine = next((g for g in games if g.take_player_id() == player_id), None)
        if mine is None:
            print(f"{tag}: player {player_id} not found, skipped")
            continue
        actions = mine.take_actions()
        masks = mine.take_masks()

        report = [e for k in cmp.parse_akino(htm) for e in k]
        rep_idx = [dist.report_action_to_index(r["player_key"]) for r in report]
        rep_keys = [r["player_key"] for r in report]

        a_syms = ["?" if x is None else str(x) for x in rep_idx]
        b_syms = [str(int(x)) for x in actions]
        sm = difflib.SequenceMatcher(a=a_syms, b=b_syms, autojunk=False)
        pairs = []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op in ("equal", "replace"):
                for k in range(min(i2 - i1, j2 - j1)):
                    pairs.append((i1 + k, j1 + k))

        ok = sum(1 for i, j in pairs
                 if rep_idx[i] is None or rep_idx[i] == int(actions[j]))
        unmatched_b = [j for j in range(len(actions)) if j not in {p[1] for p in pairs}]
        unmatched_a = [i for i in range(len(rep_idx)) if i not in {p[0] for p in pairs}]
        # are all unmatched replay rows the kan-select kind?
        all_mask1 = all(int(masks[j].sum()) == 1 for j in unmatched_b) if unmatched_b else True

        results.append((tag, len(report), len(actions), len(pairs), ok,
                        len(unmatched_b), all_mask1))
        print(f"{tag} (seat {player_id}): report {len(report):>4} | replay {len(actions):>4} "
              f"| pairs {len(pairs):>4} | agree {ok:>4}/{len(pairs):<4} "
              f"= {100.0*ok/max(1,len(pairs)):6.2f}% "
              f"| extra {len(unmatched_b):>2} (all mask#1: {all_mask1})"
              + (f" | report-unmatched {len(unmatched_a)}" if unmatched_a else ""))

    print()
    print("=== SUMMARY ===")
    tot_pairs = sum(r[3] for r in results)
    tot_ok = sum(r[4] for r in results)
    print(f"games validated : {len(results)}")
    print(f"decisions paired: {tot_pairs}")
    print(f"action agreement: {tot_ok}/{tot_pairs} = {100.0*tot_ok/max(1,tot_pairs):.2f}%")
    bad = [r for r in results if r[3] and r[4] / r[3] < 0.99]
    print(f"games below 99% : {len(bad)} {[r[0] for r in bad]}")
    print()
    if not bad:
        print("  => alignment is reliable; safe to build the distillation set.")
    else:
        print("  => exclude the flagged games from distillation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
