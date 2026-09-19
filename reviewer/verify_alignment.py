#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROVE the bigcoach->Mortal action alignment is correct.

This is the check that decides whether distillation is safe.  A wrong mapping
still trains happily and still lowers the loss -- it just teaches the model a
scrambled policy.  So we verify against ground truth instead of hoping.

Ground truth available to us:
  * our own mjai-reviewer JSON report for the same game, which records
    `actual` (the action taken) and `expected` (Mortal's argmax) straight from
    libriichi, with masks, in the same decision order.

Test 1: the report's *player* action, decoded by us, must equal `actual`.
Test 2: the report's *coach* argmax, decoded by us, must equal the action our
        Mortal report also picked, at least as often as the models agree.

If Test 1 passes at ~100%, the tile/action mapping is correct.

Usage (repo root):
    python reviewer\\verify_alignment.py [testNN ...]
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
JSON_DIR = HERE / "out" / "testset"

spec = importlib.util.spec_from_file_location("cmp", HERE / "compare_test03.py")
cmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp)

spec2 = importlib.util.spec_from_file_location("dist", HERE / "bigcoach_distill.py")
dist = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(dist)


def mortal_action_to_index(a: dict) -> int | None:
    """Action dict from a Mortal JSON report -> 46-dim index."""
    t = a.get("type")
    pai = a.get("pai")
    if t == "dahai":
        if pai is None:
            return None
        idx = dist.tile_index(pai)
        if pai.endswith("r"):
            return {4: 34, 13: 35, 22: 36}[idx]
        return idx
    if t == "reach":
        return 37
    if t == "chi":
        # our report gives the called tile + consumed; chi type by called tile
        consumed = a.get("consumed") or []
        if not consumed:
            return None
        tiles = sorted(dist.tile_index(x) for x in consumed + [pai])
        # the called tile is `pai`; chi low/mid/high depends on the run position
        nums = sorted(int(x[0]) for x in consumed + [pai] if x and x[0].isdigit())
        if len(nums) < 3:
            return None
        low = nums[0]
        return 38 if low <= 2 else (39 if low <= 5 else 40)
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


def main() -> int:
    tags = sys.argv[1:] or ["test03"]
    grand_t = grand_n = 0
    grand_c = grand_cn = 0

    for tag in tags:
        htm = next(cmp.TESTSET.glob(f"{tag}_*.htm"))
        ak = [e for k in cmp.parse_akino(htm) for e in k]
        ours, _ = cmp.load_ours(JSON_DIR / f"{tag}_finetune_step321275.json")
        o = [x for k in ours for x in k]

        if len(ak) != len(o):
            print(f"{tag}: length mismatch {len(ak)} vs {len(o)} -- skipped")
            continue

        player_ok = player_bad = 0
        coach_ok = coach_n = 0
        bad_examples = []

        for a, x in zip(ak, o):
            # Test 1: report's player action decoded == Mortal's recorded actual
            dec = dist.report_action_to_index(a["player_key"], x.get("tehai"))
            mor = mortal_action_to_index(x["actual"])
            if dec is not None and mor is not None:
                if dec == mor:
                    player_ok += 1
                else:
                    player_bad += 1
                    if len(bad_examples) < 8:
                        bad_examples.append(
                            (a["player_key"], dec, x["actual_key"], mor))

            # Test 2: report's coach argmax decoded vs Mortal's expected
            dec_c = dist.report_action_to_index(a["coach_key"], x.get("tehai"))
            mor_e = mortal_action_to_index(
                {"type": x["key"].split(":")[0],
                 "pai": x["key"].split(":")[1] if ":" in x["key"] else None})
            if dec_c is not None and mor_e is not None:
                coach_n += 1
                if dec_c == mor_e:
                    coach_ok += 1

        grand_t += player_ok + player_bad
        grand_n += player_ok
        grand_c += coach_ok
        grand_cn += coach_n

        print(f"=== {tag} ===")
        print(f"  Test 1  report player action == Mortal's actual : "
              f"{player_ok}/{player_ok+player_bad} "
              f"({100.0*player_ok/max(1,player_ok+player_bad):.1f}%)")
        print(f"  Test 2  report coach argmax  == Mortal's expected: "
              f"{coach_ok}/{coach_n} "
              f"({100.0*coach_ok/max(1,coach_n):.1f}%)")
        if bad_examples:
            print("  mismatches (report_key, our_idx, mortal_key, mortal_idx):")
            for be in bad_examples:
                print(f"      {be}")
        print()

    print("=== TOTAL ===")
    print(f"  Test 1 (alignment correctness): {grand_n}/{grand_t} = "
          f"{100.0*grand_n/max(1,grand_t):.2f}%")
    print(f"  Test 2 (coach vs our argmax)  : {grand_c}/{grand_cn} = "
          f"{100.0*grand_c/max(1,grand_cn):.2f}%")
    print()
    if grand_t and grand_n / grand_t > 0.98:
        print("  => alignment PROVEN: report actions decode onto Mortal's index space.")
    else:
        print("  => alignment SUSPECT: investigate the mismatches above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
