#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML review pages (Gokujan / bigcoach SingleFile dumps) -> distillation set.

Input  : reviewer/out/html_runs/<gid>.json      parsed by html_extract.py
         reviewer/out/html_runs/<gid>/game.mjai  converted by mjai-reviewer
         (auto-converted from tenhou_full.json if missing)

ALIGNMENT (the hard part, done right this time)
-----------------------------------------------
The review page lists, for every decision of the reviewed player, the FULL
candidate set of Akino Hana's engine: every legal action with its probability,
and the probabilities sum to 100 (verified 66/66 on the sample game).  We
replay the same game through libriichi and require EXACT set equality:

    entry candidate set  ==  the loader row's 46-dim legal-action mask

for every decision.  This is a much stronger check than the old difflib
alignment: it proves the site's enumeration and libriichi's rules agree on
every single decision before a single probability is trusted.

Two ambiguities are resolved against the mask itself (no guessing):
  * aka-dora 5m/5p/5s discards: the page renders red and normal fives
    identically; the mask tells which of 4/13/22 vs 34/35/36 is legal.
  * chi low/mid/high (38/39/40): the page lists the consumed pair only; the
    called tile tc is solved by requiring every pair to form a run with one
    common tc and the resulting index set to equal the mask's chi flags.

Output: reviewer/out/_html_staging/{logs, targets.pt} in the exact format of
export_distill.py; --merge folds it into mortal/distill (dedupe by gid).

    python reviewer\\html_to_distill.py [--gid 12d0efb1aa59fcd4] [--all]
                                       [--no-merge] [--out DIR]
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
MORTAL = ROOT / "mortal"
HTML_RUNS = HERE / "out" / "html_runs"
STAGING_DEFAULT = HERE / "out" / "_html_staging"
DISTILL = MORTAL / "distill"
REVIEWER_EXE = HERE / "mjai-reviewer-master" / "target" / "release" / "mjai-reviewer.exe"

ACTION_SPACE = 46
HONORS = ["E", "S", "W", "N", "P", "F", "C"]
AKA_OF = {"5m": 34, "5p": 35, "5s": 36}   # aka slots: base + 30

SUMMARY_TURN_RE = re.compile(r"(\d+)巡")


def tile_index(t: str) -> int:
    t = t.replace("r", "")
    if len(t) == 2 and t[0].isdigit() and t[1].islower():
        return {"m": 0, "p": 9, "s": 18}[t[1]] + int(t[0]) - 1
    return 27 + HONORS.index(t.upper())


# --------------------------------------------------------------------------- #
# entry -> 46-dim index plan, resolved and verified against a row's mask
# --------------------------------------------------------------------------- #
def resolve_chi(pairs: list[tuple[int, int]], mask: set[int]):
    """Map each consumed pair to chi low/mid/high, or None if inconsistent."""
    mask_chi = mask & {38, 39, 40}
    if not pairs:
        return {} if not mask_chi else None
    for tc in range(37):
        plan, ok = {}, True
        for lo, hi in pairs:
            s = sorted((lo, hi, tc))
            if not (s[0] // 9 == s[2] // 9 and s[1] == s[0] + 1
                    and s[2] == s[1] + 1):
                ok = False
                break
            plan[(lo, hi)] = 38 if tc < lo else (39 if tc < hi else 40)
        if ok and set(plan.values()) == mask_chi:
            return plan
    return None


def resolve_discard(name: str, mask: set[int]) -> int | None:
    """Tile name -> discard slot; aka resolved by the mask.

    A trailing '*' marks an explicit red five (API reviews carry '5mr');
    it maps straight to the aka slot 34/35/36 when legal in the mask.
    """
    if name.endswith("*"):
        base = name[:-1]
        if base in AKA_OF and AKA_OF[base] in mask:
            return AKA_OF[base]
        return None
    if name.endswith("n"):
        # explicit normal five (API reviews: pai without 'r'); the aka slot
        # is used only when the normal slot is illegal (never expected)
        base = name[:-1]
        idx = tile_index(base)
        if base in AKA_OF and idx in mask:
            return idx
        return None
    t = name.replace("r", "")
    idx = tile_index(t)
    if t in AKA_OF:
        cands = [i for i in (idx, AKA_OF[t]) if i in mask]
        if len(cands) == 1:
            return cands[0]
        if len(cands) == 2:      # both normal and red five are legal -> ??
            return None
        return idx               # neither: inconsistent, set-check will reject
    return idx


def entry_plan(entry: dict, mask: set[int]) -> dict | None:
    """candidate row index -> 46-dim action index, iff sets match exactly."""
    plan: dict[int, int] = {}
    chi_pairs: list[tuple[int, int]] = []
    chi_plan: dict = {}
    for k, c in enumerate(entry["candidates"]):
        lab = c["label"]
        if lab == "跳过":
            plan[k] = 45
        elif lab == "流局":
            plan[k] = 44
        elif lab == "立直":
            plan[k] = 37
        elif lab == "和":
            plan[k] = 43
        elif lab == "杠":
            plan[k] = 42
        elif lab == "碰":
            plan[k] = 41
        elif lab == "吃":
            ts = [tile_index(t) for t in c["tiles"]]
            if len(ts) != 2:
                return None
            lo, hi = sorted(ts)
            if not (0 <= lo < hi <= 26 and hi - lo <= 2):
                return None
            chi_pairs.append((lo, hi))
        elif lab == "打":
            idx = resolve_discard(c["tile"], mask)
            if idx is None:
                return None
            plan[k] = idx
        else:
            return None
    if chi_pairs:
        chi_plan = resolve_chi(chi_pairs, mask)
        if chi_plan is None:
            return None
        for k, c in enumerate(entry["candidates"]):
            if c["label"] == "吃":
                lo, hi = sorted(tile_index(t) for t in c["tiles"])
                plan[k] = chi_plan[(lo, hi)]
    if set(plan.values()) == mask:
        return plan
    return None


# --------------------------------------------------------------------------- #
# align entries to replay rows for one seat
# --------------------------------------------------------------------------- #
def align_entries(entries, rowsets, n_rows):
    """Greedy chronological matching; returns (pairs, unmatched, ambiguous)."""
    pairs, r = [], 0
    for e_i, entry in enumerate(entries):
        while r < n_rows and entry_plan(entry, rowsets[r]) is None:
            r += 1
        if r >= n_rows:
            return pairs, len(entries) - len(pairs), None
        pairs.append((e_i, r))
        r += 1
    return pairs, 0, None


# --------------------------------------------------------------------------- #
def convert_game(gid: str, html_runs: pathlib.Path) -> pathlib.Path | None:
    """Ensure game.mjai exists; run mjai-reviewer when only tenhou_full.json."""
    mjai = html_runs / gid / "game.mjai"
    if mjai.is_file():
        return mjai
    tenhou = html_runs / gid / "tenhou_full.json"
    if not tenhou.is_file():
        return None
    print(f"    converting tenhou -> mjai ({gid})")
    subprocess.run([str(REVIEWER_EXE), "-i", str(tenhou), "--mjai-out",
                    str(mjai), "--no-review"], check=True, capture_output=True)
    if not mjai.is_file():
        return None
    return mjai


def main() -> int:
    import numpy as np
    import torch

    ap = argparse.ArgumentParser()
    ap.add_argument("--gid", action="append", help="process only these ids")
    ap.add_argument("--out", type=pathlib.Path, default=STAGING_DEFAULT)
    ap.add_argument("--no-merge", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--html-dir", type=pathlib.Path, default=HTML_RUNS)
    args = ap.parse_args()

    args.out = args.out.resolve()
    log_dir = args.out / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    if args.gid:
        files = sorted(args.html_dir.glob("*.json"))
        files = [f for f in files if f.stem in args.gid]
    else:
        files = sorted(f for f in args.html_dir.glob("*.json")
                       if not f.name.startswith("_"))
    if args.limit:
        files = files[:args.limit]
    if not files:
        print(f"no reviews under {args.html_dir}")
        return 1
    print(f"{len(files)} review(s) -> {args.out}")

    prev = os.getcwd()
    os.chdir(MORTAL)
    sys.path.insert(0, str(MORTAL))
    from libriichi.dataset import GameplayLoader
    loader = GameplayLoader(version=4, player_names=[], excludes=[],
                            augmented=False)
    os.chdir(prev)

    targets = {}
    per_game = []
    total_rows = total_valid = 0
    reasons = collections.Counter()

    for i, f in enumerate(files, 1):
        gid = f.stem
        obj = json.loads(f.read_text(encoding="utf-8"))
        entries = obj.get("entries") if isinstance(obj, dict) else obj
        mjai_path = convert_game(gid, args.html_dir)
        if mjai_path is None:
            reasons["no game.mjai/tenhou_full.json"] += 1
            continue
        raw = mjai_path.read_text(encoding="utf-8")

        events = [json.loads(x) for x in raw.splitlines() if x.strip()]
        os.chdir(MORTAL)
        try:
            games = loader.load_log(raw)
        except Exception as ex:
            os.chdir(prev)
            reasons[f"load failed: {str(ex)[:60]}"] += 1
            continue
        os.chdir(prev)

        seat, best = None, None
        for g in games:
            actions = g.take_actions()
            masks = list(g.take_masks())
            kyokus = g.take_at_kyoku()
            turns = g.take_at_turns()
            seats_rowsets = [frozenset(int(j) for j in np.nonzero(m)[0].tolist())
                             for m in masks]
            pairs, unmatched, _ = align_entries(entries, seats_rowsets,
                                                len(actions))
            score = (len(pairs), -unmatched)
            if best is None or score > best[0]:
                seat = int(g.take_player_id())
                best = (score, pairs, seats_rowsets, len(actions),
                        actions, kyokus, turns)

        pairs = best[1]
        if len(pairs) != len(entries):
            reasons["alignment incomplete"] += 1
            print(f"[{i}/{len(files)}] {gid}: FAIL "
                  f"(matched {len(pairs)}/{len(entries)})")
            continue
        rowsets = best[2]
        n_rows = best[3]
        actions = best[4]
        kyokus = best[5]
        turns = best[6]

        tgt = np.zeros((n_rows, ACTION_SPACE), dtype=np.float32)
        val = np.zeros((n_rows,), dtype=bool)
        n_invalid = 0
        for e_i, r_i in pairs:
            e = entries[e_i]
            plan = entry_plan(e, rowsets[r_i])
            if plan is None:
                n_invalid += 1
                continue
            row = np.zeros(ACTION_SPACE, dtype=np.float32)
            for k, c in enumerate(e["candidates"]):
                row[plan[k]] += float(c["prob"])
            if row.sum() <= 0:
                n_invalid += 1
                continue
            tgt[r_i] = row / row.sum()
            val[r_i] = True

        # ---- independent cross-checks (report only) ---------------------- #
        rank_ok = rank_bad = turn_ok = turn_bad = 0
        for e_i, r_i in pairs:
            e = entries[e_i]
            m = SUMMARY_TURN_RE.search(e.get("summary") or "")
            if m:
                exp_turn = int(m.group(1))
                if turns[r_i] == exp_turn:
                    turn_ok += 1
                else:
                    turn_bad += 1
            rk = e.get("rank")
            if rk is not None:
                act = int(actions[r_i])
                p_act = float(tgt[r_i][act])
                r_here = 1 + int((tgt[r_i] > p_act).sum())
                if r_here == int(rk):
                    rank_ok += 1
                else:
                    rank_bad += 1

        key = f"{gid}_s{seat}"
        targets[key] = {"target": torch.from_numpy(tgt),
                        "valid": torch.from_numpy(val)}
        gz = log_dir / f"{key}.json.gz"
        with gzip.open(gz, "wt", encoding="utf-8", newline="\n") as fh:
            for ev in events:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")

        nv = int(val.sum())
        total_rows += n_rows
        total_valid += nv
        per_game.append((gid, seat, len(entries), n_rows, nv, n_invalid,
                         rank_ok, rank_bad, turn_ok, turn_bad))

        if i % 10 == 0 or i == len(files):
            print(f"  [{i}/{len(files)}] ok={len(targets)} "
                  f"rows={total_rows:,} valid={total_valid:,}")

    torch.save({"games": targets,
                "meta": {"games": len(targets), "rows": total_rows,
                         "valid_rows": total_valid,
                         "source": "gokujan-html"}},
               args.out / "targets.pt")

    print()
    print("=== per-game summary ===")
    print(f"  {'gid':<18} {'seat':<4} {'entries':<7} {'rows':<5} "
          f"{'valid':<6} {'badE':<4} {'rankOk':<6} {'rankBad':<7} "
          f"{'turnOk':<6} {'turnBad':<7}")
    for gid, seat, ne, nr, nv, nb, rok, rbad, tok, tbad in per_game:
        print(f"  {gid:<18} {seat:<4} {ne:<7} {nr:<5} {nv:<6} {nb:<4} "
              f"{rok:<6} {rbad:<7} {tok:<6} {tbad:<7}")
    print()
    print(f"=== exported ===")
    print(f"  games        : {len(targets)}")
    print(f"  replay rows  : {total_rows:,}")
    print(f"  valid targets: {total_valid:,} "
          f"({100.0*total_valid/max(1, total_rows):.1f}% of rows)")
    print(f"  staging      : {args.out}")
    if reasons:
        for k, v in reasons.most_common():
            print(f"  {v:4}x {k}")

    if args.no_merge:
        return 0

    # ---- merge into mortal/distill --------------------------------------- #
    print("\nmerging into mortal/distill")
    dst_logs = DISTILL / "logs"
    dst_logs.mkdir(parents=True, exist_ok=True)
    added = 0
    for f in sorted(log_dir.glob("*.json.gz")):
        if not (dst_logs / f.name).exists():
            shutil.copy2(f, dst_logs / f.name)
            added += 1
    dst_t = DISTILL / "targets.pt"
    if dst_t.is_file():
        old = torch.load(dst_t, weights_only=False)
        games = old.get("games", {})
        meta = old.get("meta", {})
    else:
        games, meta = {}, {}
    merged = 0
    for k, v in targets.items():
        if k not in games:
            games[k] = v
            merged += 1
    meta["games"] = len(games)
    meta["valid_rows"] = int(sum(v["valid"].sum().item()
                                 for v in games.values()))
    torch.save({"games": games, "meta": meta}, dst_t)
    print(f"   logs added: {added}   targets merged: {merged}   "
          f"total games now: {meta['games']}   valid rows: {meta['valid_rows']:,}")
    (args.out / "targets.pt").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())