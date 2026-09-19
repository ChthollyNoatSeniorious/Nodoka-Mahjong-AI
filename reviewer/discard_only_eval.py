"""Recompute the 10-game test-set deviation on REAL DISCARD DECISIONS ONLY.

The headline metric (mjai-reviewer's total_matches/total_reviewed) counts every
reviewed decision, including decisions where the human had no legal action and
the model therefore had nothing to choose.  Both Akino Hana and our model get
those for free, which compresses the difference between them.

This script separates the two so we can see which checkpoint is really closer to
Akino Hana on decisions that involve an actual choice.

Usage (repo root):  python reviewer\\discard_only_eval.py
"""
from __future__ import annotations

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
JSON_DIR = HERE / "out" / "testset"
TESTSET = ROOT / "Test set"
NAME_RE = re.compile(r"^(test\d+)_(.+?)_([\d.]+)%_(\d+)-(\d+)\.htm$", re.IGNORECASE)

CHECKPOINTS = [
    ("2024v4best (base)", "test0{n}_2024v4best.json"),
    ("finetune 107,091", "test0{n}_finetune_step107091_agree85.17.json"),
    ("finetune 214,183", "test0{n}_finetune_step214183_agree88.57.json"),
    ("finetune 321,275 (adopted)", "test0{n}_finetune_step321275.json"),
    ("finetune 428,367", "test0{n}_finetune_step428367.json"),
]


def parse_cases():
    cases = []
    for f in sorted(TESTSET.glob("*.htm")):
        m = NAME_RE.match(f.name)
        if not m:
            continue
        tag, log_and_tw, pct, matches, total = m.groups()
        cases.append({
            "tag": tag, "n": int(tag[4:]),
            "base_matches": int(matches), "base_total": int(total),
        })
    return cases


def decompose(path: pathlib.Path):
    """-> (all_matches, all_total, discard_matches, discard_total)"""
    d = json.loads(path.read_text(encoding="utf-8"))
    ent = [e for k in d["review"]["kyokus"] for e in k["entries"]]
    all_m = sum(1 for e in ent if e["is_equal"])
    dah = [e for e in ent if e["actual"]["type"] == "dahai"]
    dah_m = sum(1 for e in dah if e["is_equal"])
    return all_m, len(ent), dah_m, len(dah)


def main():
    cases = parse_cases()

    # baseline per case, decomposed from the filename numbers:
    # we only know the headline; the forced-pass count is derived from our own
    # reports, which carry the human's action, so it is model independent.
    print("case   AkinoHana(headline)   ", end="")
    for name, _ in CHECKPOINTS:
        print("%22s" % name[:22], end="")
    print()

    totals = {name: [0, 0, 0, 0] for name, _ in CHECKPOINTS}
    base_all = [0, 0]
    base_dah = [0, 0]

    for c in cases:
        n = c["n"]
        ref = JSON_DIR / f"test0{n}_finetune_step321275.json"
        if not ref.is_file():
            print(f"{c['tag']} : reference json missing")
            continue
        _, all_t, _, dah_t = decompose(ref)

        # Akino Hana's discard-only count is not in the filename.  Derive it the
        # same way for every case: headline minus the forced-pass decisions that
        # are free for everyone (Akino Hana always "agrees" on a forced pass).
        forced = all_t - dah_t
        ak_dah_m = c["base_matches"] - forced
        base_all[0] += c["base_matches"]
        base_all[1] += all_t
        base_dah[0] += ak_dah_m
        base_dah[1] += dah_t

        print(f"{c['tag']}  {c['base_matches']:>4}/{all_t:<4} "
              f"({100.0*c['base_matches']/all_t:5.1f}%)  "
              f"| discards {ak_dah_m:>4}/{dah_t:<4} ", end="")
        for name, pat in CHECKPOINTS:
            p = JSON_DIR / pat.format(n=n)
            if not p.is_file():
                print("%22s" % "missing", end="")
                continue
            am, at, dm, dt = decompose(p)
            totals[name][0] += am
            totals[name][1] += at
            totals[name][2] += dm
            totals[name][3] += dt
            print("%20.1f%%" % (100.0 * dm / dt), end="  ")
        print()

    print()
    print("=== TOTALS over %d games ===" % len(cases))
    ak_all = 100.0 * base_all[0] / base_all[1]
    ak_dah = 100.0 * base_dah[0] / base_dah[1]
    print("Akino Hana   headline %d/%d = %.2f%%   |   discards %d/%d = %.2f%%"
          % (base_all[0], base_all[1], ak_all,
             base_dah[0], base_dah[1], ak_dah))
    print()
    print("%-28s %10s %10s %10s %10s" % (
        "model", "headline", "dev(head)", "discard", "dev(disc)"))
    print("-" * 72)
    for name, _ in CHECKPOINTS:
        am, at, dm, dt = totals[name]
        h = 100.0 * am / at
        dd = 100.0 * dm / dt
        print("%-28s %9.2f%% %+9.2f %9.2f%% %+9.2f" % (
            name, h, h - ak_all, dd, dd - ak_dah))
    return 0


if __name__ == "__main__":
    sys.exit(main())
