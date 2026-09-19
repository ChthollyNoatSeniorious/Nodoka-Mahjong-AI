#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a DISTILLATION dataset from bigcoach classic reports.

Each sample is a pair (observation, Akino Hana's action distribution):

    obs      : (1012, 34) float32   -- exactly what train.py feeds the model
    target   : (46,)      float32   -- pi over Mortal's action space, sums to 1
    mask     : (46,)      bool      -- legal actions
    label    : int                  -- the action actually taken (for sanity checks)

`target` is the whole point: instead of a one-hot "it played 1s", the model
learns the full distribution, which is the only way to match Akino Hana on the
~78% of decisions that have more than one plausible choice.

ALIGNMENT
---------
The report lists one decision per row; libriichi's replay emits extra rows for
kan tile-selection.  We align them with difflib sequence matching, which was
validated at 100% (2135/2135 decisions, 10 games) by `validate_alignment.py`.
Games that fail to align cleanly are skipped rather than silently mislabelled.

USAGE
-----
    # from the 10 existing test reports (no network needed)
    python reviewer\\build_distill_set.py --from-testset -o reviewer\\out\\distill_test.pt

    # from harvested reports + their mjai logs
    python reviewer\\build_distill_set.py --reports DIR --logs DIR -o dataset.pt
"""

from __future__ import annotations

import argparse
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

spec = importlib.util.spec_from_file_location("cmp", HERE / "compare_test03.py")
cmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp)
spec2 = importlib.util.spec_from_file_location("dist", HERE / "bigcoach_distill.py")
dist = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(dist)

ACTION_SPACE = 46


def alignment_pairs(rep_idx: list[int | None], actions) -> list[tuple[int, int]]:
    """Pair report rows with replay rows, tolerating the extra kan-select rows."""
    a = ["?" if x is None else str(x) for x in rep_idx]
    b = [str(int(x)) for x in actions]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    pairs = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ("equal", "replace"):
            for k in range(min(i2 - i1, j2 - j1)):
                pairs.append((i1 + k, j1 + k))
    return pairs


def build_target(cands, hand, called):
    """report candidates -> (normalised 46-dim target, dropped mass fraction).

    `dropped` is the fraction of this decision's probability mass that could not
    be mapped onto the action space.  Chi candidates are ambiguous when the
    discarder's tile is unknown and the hand does not disambiguate; if such a
    candidate is dominant (e.g. pi=91 for a chi the player declined), the
    renormalised target would claim Akino Hana wanted to pass -- the opposite of
    the truth.  The caller drops those samples.
    """
    import numpy as np
    t = np.zeros(ACTION_SPACE, dtype=np.float32)
    total = 0.0
    for c in cands:
        total += c["pi"]
        idx = dist.report_action_to_index(c["key"], hand, called)
        if idx is None:
            continue
        t[idx] += c["pi"] / 100.0
    s = t.sum()
    dropped = 0.0
    if total > 0:
        dropped = max(0.0, 1.0 - (s / (total / 100.0)))
    if s > 0:
        t /= s
    return t, dropped


def player_chi_calls(events: list, player_id: int) -> list[str]:
    """Ordered list of called tiles for this player's chi actions.

    The k-th chi decision in the report corresponds to the k-th chi event in the
    log, so this resolves low/mid/high exactly instead of guessing from the hand.
    """
    out = []
    for ev in events:
        if ev.get("type") == "chi" and ev.get("actor") == player_id:
            pai = ev.get("pai")
            if pai:
                out.append(pai)
    return out


def process_game(report_path: pathlib.Path, mjai_events: list, player_id: int,
                 verbose: bool = False):
    """-> (obs, targets, masks, labels, stats) or None if unusable."""
    import numpy as np

    # libriichi is imported from the mortal directory.  We must not leave the
    # process cwd changed, or a relative --out would resolve against it.
    prev_cwd = os.getcwd()
    os.chdir(MORTAL)
    sys.path.insert(0, str(MORTAL))
    try:
        from libriichi.dataset import GameplayLoader
    finally:
        pass

    gz = TMP / f"{report_path.stem[:40]}_replay.json.gz"
    TMP.mkdir(parents=True, exist_ok=True)
    with gzip.open(gz, "wt", encoding="utf-8", newline="\n") as fh:
        for ev in mjai_events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")

    loader = GameplayLoader(version=4, player_names=[], excludes=[], augmented=False)
    data = loader.load_gz_log_files([str(gz)])
    games = [g for grp in data for g in grp]
    mine = next((g for g in games if g.take_player_id() == player_id), None)
    if mine is None:
        return None

    obs = mine.take_obs()
    actions = mine.take_actions()
    masks = mine.take_masks()

    report = [e for k in cmp.parse_akino(report_path) for e in k]
    if not report:
        return None
    rep_idx = [dist.report_action_to_index(r["player_key"]) for r in report]

    pairs = alignment_pairs(rep_idx, actions)
    if len(pairs) != len(report):
        if verbose:
            print(f"    alignment incomplete: {len(pairs)}/{len(report)}")
        return None

    # trust check: every report row must land on a replay row whose action matches
    agree = sum(1 for i, j in pairs
                if rep_idx[i] is None or rep_idx[i] == int(actions[j]))
    if agree / len(pairs) < 0.99:
        if verbose:
            print(f"    alignment agreement too low: {agree}/{len(pairs)}")
        return None

    o_list, t_list, m_list, l_list = [], [], [], []
    dropped_samples = 0
    worst_drop = 0.0
    chi_calls = player_chi_calls(mjai_events, player_id)
    chi_i = 0
    for i, j in pairs:
        r = report[i]
        # if this row is a chi, take the called tile from the log (exact);
        # every chi candidate at this row shares that called tile.
        called = None
        if r["player_key"].startswith("chi:") and chi_i < len(chi_calls):
            called = chi_calls[chi_i]
            chi_i += 1
        target, dropped = build_target(r["cands"], None, called)
        if dropped > 0.05:
            # too much mass unmapped: the target would be misleading, so skip it
            dropped_samples += 1
            worst_drop = max(worst_drop, dropped)
            continue
        if target.sum() <= 0:
            continue
        o_list.append(np.asarray(obs[j], dtype=np.float32))
        t_list.append(target)
        m_list.append(np.asarray(masks[j], dtype=bool))
        l_list.append(int(actions[j]))

    if not o_list:
        os.chdir(prev_cwd)
        return None
    result = (np.stack(o_list), np.stack(t_list), np.stack(m_list),
              np.asarray(l_list, dtype=np.int64),
              {"rows": len(o_list), "dropped": dropped_samples,
               "worst_drop": worst_drop, "chi_calls": len(chi_calls)})
    os.chdir(prev_cwd)
    return result


def main() -> int:
    import numpy as np
    import torch

    ap = argparse.ArgumentParser()
    ap.add_argument("--from-testset", action="store_true",
                    help="use the 10 test reports + their embedded mjai logs")
    ap.add_argument("--reports", type=pathlib.Path,
                    help="directory of harvested .htm reports")
    ap.add_argument("--logs", type=pathlib.Path,
                    help="directory of mjai .json.gz logs (for harvested reports)")
    ap.add_argument("-o", "--out", type=pathlib.Path, required=True)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    # resolve BEFORE anything can change the working directory (libriichi needs
    # cwd=mortal, which would otherwise silently redirect a relative --out)
    args.out = args.out.resolve()
    if args.reports:
        args.reports = args.reports.resolve()
    if args.logs:
        args.logs = args.logs.resolve()

    jobs = []          # (report_path, events, player_id)
    if args.from_testset:
        for n in range(1, 11):
            tag = f"test{n:02d}"
            jf = JSON_DIR / f"{tag}_finetune_step321275.json"
            if not jf.is_file():
                continue
            rep = json.loads(jf.read_text(encoding="utf-8"))
            log = rep.get("mjai_log")
            if not log:
                continue
            events = ([json.loads(x) for x in log.splitlines() if x.strip()]
                      if isinstance(log, str) else log)
            jobs.append((next(cmp.TESTSET.glob(f"{tag}_*.htm")), events,
                         rep.get("player_id", 0)))
    else:
        if not (args.reports and args.logs):
            print("need --reports and --logs (or --from-testset)", file=sys.stderr)
            return 2
        for htm in sorted(args.reports.glob("*.htm")):
            gz = args.logs / f"{htm.stem}.json.gz"
            if not gz.is_file():
                if args.verbose:
                    print(f"  no log for {htm.name}")
                continue
            with gzip.open(gz, "rt", encoding="utf-8") as fh:
                events = [json.loads(x) for x in fh if x.strip()]
            jobs.append((htm, events, 0))

    print(f"{len(jobs)} game(s) to convert")
    print()

    O, T, M, L = [], [], [], []
    used = skipped = 0
    total_rows = 0
    for htm, events, pid in jobs:
        print(f"  {htm.name[:60]} (seat {pid})")
        try:
            r = process_game(htm, events, pid, verbose=args.verbose)
        except Exception as exc:
            print(f"    ERROR: {exc}")
            r = None
        if r is None:
            skipped += 1
            print("    skipped")
            continue
        o, t, m, l, st = r
        O.append(o); T.append(t); M.append(m); L.append(l)
        used += 1
        total_rows += st["rows"]
        extra = ""
        if st["dropped"]:
            extra = (f"  (dropped {st['dropped']} ambiguous-chi samples, "
                     f"worst mass lost {100*st['worst_drop']:.0f}%)")
        print(f"    {st['rows']} samples{extra}")

    if not O:
        print("\nno usable games")
        return 1

    obs = torch.from_numpy(np.concatenate(O))
    target = torch.from_numpy(np.concatenate(T))
    mask = torch.from_numpy(np.concatenate(M))
    label = torch.from_numpy(np.concatenate(L))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "obs": obs, "target": target, "mask": mask, "label": label,
        "meta": {"games": used, "skipped": skipped, "rows": int(obs.shape[0]),
                 "source": "testset" if args.from_testset else "harvested"},
    }, args.out)

    print()
    print(f"=== saved {args.out} ===")
    print(f"  games used     : {used} (skipped {skipped})")
    print(f"  samples        : {obs.shape[0]}")
    print(f"  obs            : {tuple(obs.shape)}")
    print(f"  target         : {tuple(target.shape)}  sum={target.sum(-1).mean():.4f}")
    print(f"  mask           : {tuple(mask.shape)}  legal/sample={mask.sum(-1).float().mean():.2f}")
    # sanity: is the label inside the target's support?
    inside = (target.gather(1, label.view(-1, 1)).squeeze(1) > 0).float().mean()
    top1 = target.argmax(-1)
    print(f"  label has pi>0 : {inside*100:.1f}% of samples")
    print(f"  argmax==label  : {(top1 == label).float().mean()*100:.1f}% "
          f"(low is EXPECTED: target is Akino Hana, label is the human)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
