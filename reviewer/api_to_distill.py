#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API review JSON (review.bigcoach.work) -> html_extract-format runs, then
feed the existing html_to_distill.py conversion+merge pipeline.

The API data JSON (fetched by fetch_api_reviews.py) carries everything the
HTML snapshot carried, in a cleaner shape:

    review.kyokus[].entries[]:
        details[]: {action: mjai-action, prob}   full candidate distribution
        state:     {tehai, fuuros}               hand at decision time
        actual/expected, actual_index, junme, tiles_left

This script rewrites each game into:

    out/html_runs/<id>.json             html_extract.py output format
    out/html_runs/<id>/game.mjai        mjai_log serialized as JSONL

and then invokes html_to_distill.py --gid <id> ... (which replays the game
with libriichi, aligns every entry to a loader row by exact mask-set
equality, converts probabilities into 46-dim targets and merges into
mortal/distill).

Differences handled here (vs the HTML snapshots):
  * actions compare on type+pai/consumed/target, ignoring tsumogiri flags
    and hora deltas/ura_markers (the site sometimes marks the same discard
    with different tsumogiri values).
  * red fives are explicit: pai '5mr' -> tile '5m*'; html_to_distill's
    resolve_discard maps '*' to the aka slot 34/35/36 directly.
  * no "N巡" summary -> the turn cross-check is skipped for API games
    (rank cross-check against detail probabilities still runs).
"""
from __future__ import annotations

import argparse
import collections
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

HERE = pathlib.Path(__file__).resolve().parent
API_RUNS = HERE / "out" / "api_runs"
HTML_RUNS = HERE / "out" / "html_runs"

NA = {"hora", "none", "reach"}

PLAN_LABELS = {"打", "跳过", "立直", "和", "杠", "碰", "吃"}


def norm_action(a: dict) -> tuple:
    """Canonical key for matching details actions against actual/expected."""
    t = a.get("type")
    if t == "dahai":
        return ("dahai", a.get("pai"))
    if t == "chi":
        return ("chi", tuple(sorted(a.get("consumed") or [])))
    if t == "pon":
        return ("pon", tuple(sorted(a.get("consumed") or [])),
                a.get("target"))
    if t in ("ankan", "daiminkan", "kakan"):
        return (t, a.get("pai"))
    if t == "hora":
        return ("hora", a.get("target"))
    return (t,)


def action_label(a: dict) -> str | None:
    t = a.get("type")
    if t == "dahai":
        return "打"
    if t == "none":
        return "跳过"
    if t == "reach":
        return "立直"
    if t == "hora":
        return "和"
    if t == "ryukyoku":
        return "流局"
    if t in ("ankan", "daiminkan", "kakan"):
        return "杠"
    if t == "pon":
        return "碰"
    if t == "chi":
        return "吃"
    return None


def to_html_entry(e: dict) -> dict | None:
    """API entry -> html_extract entry (candidates with label/tile/prob)."""
    cands = []
    seen_idx = set()
    for det in e.get("details", []):
        a = det.get("action") or {}
        lab = action_label(a)
        if lab is None:
            return None
        if lab == "打":
            pai = a.get("pai") or ""
            if pai.endswith("r") and len(pai) == 3:
                tile = pai[0] + pai[1] + "*"
            elif len(pai) == 2 and pai[0] == "5" and pai[1] in "mps":
                tile = pai + "n"
            else:
                tile = pai
            cands.append({"label": "打", "tile": tile, "tiles": [tile],
                          "prob": float(det["prob"]) * 100.0})
        elif lab == "吃":
            tiles = list(a.get("consumed") or [])
            cands.append({"label": "吃", "tile": None, "tiles": tiles,
                          "prob": float(det["prob"]) * 100.0})
        else:
            cands.append({"label": lab, "tile": None, "tiles": [],
                          "prob": float(det["prob"]) * 100.0})
        seen_idx.add(norm_action(a))

    # rank: position of actual within the detail distribution
    act = e.get("actual")
    rank = None
    p_act = None
    if act is not None and norm_action(act) in seen_idx:
        kact = norm_action(act)
        for det in e.get("details", []):
            if norm_action(det["action"]) == kact:
                p_act = float(det["prob"])
                break
        if p_act is not None:
            rank = 1 + sum(1 for det in e.get("details", [])
                           if float(det["prob"]) > p_act)
    if rank is None and e.get("actual_index") is not None:
        rank = int(e["actual_index"]) + 1

    state = e.get("state") or {}
    hand = [t.upper() for t in (state.get("tehai") or [])]
    return {
        "mark_red": rank is not None,
        "summary": None,
        "turn_info": "",
        "rank": rank,
        "n_candidates": len(cands),
        "shanten_text": f"shanten={e.get('shanten')}",
        "hand": hand,
        "roles": [],
        "candidates": cands,
        "prob_sum": round(sum(c["prob"] for c in cands), 3),
        "prob_sum_ok": abs(sum(c["prob"] for c in cands) - 100.0) < 1e-3,
    }


def convert_one(rid: str, force: bool) -> tuple[bool, str]:
    src = API_RUNS / f"{rid}.json"
    if not src.is_file():
        return False, "no api json"
    j = json.loads(src.read_text(encoding="utf-8"))
    kyokus = j.get("review", {}).get("kyokus", [])
    entries = []
    for k in kyokus:
        for e in k.get("entries", []):
            he = to_html_entry(e)
            if he is None:
                return False, "unknown action label"
            entries.append(he)
    out = {
        "source": "api",
        "api_url": f"https://review.bigcoach.work/review/{rid}",
        "gid": rid,
        "engine": "RIGEL 1.4",
        "n_kyoku": len(kyokus),
        "entries": entries,
        "n_entries": len(entries),
        "warnings": [],
    }
    hr = HTML_RUNS / f"{rid}.json"
    hr.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    mjai = j.get("mjai_log") or []
    mdir = HTML_RUNS / rid
    mdir.mkdir(parents=True, exist_ok=True)
    gm = mdir / "game.mjai"
    if force or not gm.is_file():
        with gm.open("w", encoding="utf-8", newline="\n") as fh:
            for ev in mjai:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return True, "converted"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--gid", action="append")
    ap.add_argument("--no-convert", action="store_true",
                    help="skip running html_to_distill")
    ap.add_argument("--no-merge", action="store_true",
                    help="pass --no-merge to html_to_distill")
    args = ap.parse_args()

    if args.gid:
        ids = args.gid
    elif args.all:
        ids = sorted(p.stem for p in API_RUNS.glob("*.json")
                     if not p.name.endswith(".meta.json")
                     and not p.name.startswith("_"))
    else:
        print("need --gid or --all")
        return 2
    print(f"converting {len(ids)} api games -> html format")

    conv_ok, reasons = 0, collections.Counter()
    for rid in ids:
        ok, why = convert_one(rid, force=False)
        if ok:
            conv_ok += 1
            print(f"  {rid}: converted ({why})")
        else:
            reasons[why] += 1
            print(f"  {rid}: FAIL {why}")

    if args.no_convert:
        print(f"converted {conv_ok}/{len(ids)} (skip html_to_distill)")
        return 0

    if conv_ok:
        # prefer mortal/.venv (has torch/numpy) over the system interpreter
        venv_py = HERE.parent / "mortal" / ".venv" / "Scripts" / "python.exe"
        py = str(venv_py) if venv_py.exists() else sys.executable
        cmd = [py, str(HERE / "html_to_distill.py")]
        for rid in ids:
            cmd += ["--gid", rid]
        if args.no_merge:
            cmd += ["--no-merge"]
        print("running:", " ".join(cmd))
        r = subprocess.run(cmd, cwd=HERE.parent)
        return r.returncode
    return 1


if __name__ == "__main__":
    sys.exit(main())