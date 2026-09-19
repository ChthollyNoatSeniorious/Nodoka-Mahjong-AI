#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evaluate Mortal checkpoints on the held-out human-log test set.

`Test set/` contains 10 *human* Tenhou games plus, encoded in each filename, the
agreement rate that the **Akino Hana** model achieves against that human play:

    testNN_<tenhou log id>&tw=<seat>_<agreement>%_<matches>-<total>.htm

This script re-downloads each log, reviews it with the given checkpoint(s) via
`review.py`, and reports the agreement so it can be compared with the Akino Hana
baseline. Because the logs are human games (the training data is Akino Hana
self-play), this measures whether the style imitation *generalises* rather than
memorising the training set.

Usage (from the repo root):

    python reviewer\\testset_eval.py <model.pth> [<model2.pth> ...]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TESTSET = ROOT / "Test set"
OUT_DIR = HERE / "out" / "testset"
REVIEW_PY = HERE / "review.py"
PY = ROOT / ".venv" / "Scripts" / "python.exe"

NAME_RE = re.compile(r"^(test\d+)_(.+?)_([\d.]+)%_(\d+)-(\d+)\.htm$", re.IGNORECASE)


def parse_cases():
    cases = []
    for f in sorted(TESTSET.glob("*.htm")):
        m = NAME_RE.match(f.name)
        if not m:
            print(f"[warn] cannot parse filename: {f.name}", file=sys.stderr)
            continue
        tag, log_and_tw, pct, matches, total = m.groups()
        log_id, _, tw = log_and_tw.partition("&tw=")
        cases.append({
            "tag": tag,
            "log_id": log_id,
            "tw": int(tw) if tw else 0,
            "url": f"https://tenhou.net/3/?log={log_id}&tw={tw or 0}",
            "base_pct": float(pct),
            "base_matches": int(matches),
            "base_total": int(total),
        })
    return cases


def review_one(model: Path, case: dict, tag_suffix: str) -> dict:
    out_json = OUT_DIR / f"{case['tag']}_{tag_suffix}.json"
    cmd = [
        str(PY), "-u", str(REVIEW_PY),
        "-u", case["url"],
        "-m", str(model),
        "--json",
        "--no-open",
        "-o", str(out_json),
    ]
    proc = None
    for attempt in range(3):
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode == 0 and out_json.is_file():
            break
        # transient failures happen (log download hiccups / contention): retry
        if out_json.is_file():
            out_json.unlink()
    if proc is None or proc.returncode != 0 or not out_json.is_file():
        code = proc.returncode if proc else "?"
        return {"error": f"exit {code}", "stderr": (proc.stderr or "")[-400:] if proc else ""}
    try:
        data = json.loads(out_json.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"cannot read report: {exc}"}
    rev = data.get("review", {})
    return {
        "matches": rev.get("total_matches"),
        "total": rev.get("total_reviewed"),
        "rating": rev.get("rating"),
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    models = [Path(a) for a in sys.argv[1:]]
    for m in models:
        if not m.is_file():
            print(f"model not found: {m}", file=sys.stderr)
            return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = parse_cases()
    if not cases:
        print("no test cases found", file=sys.stderr)
        return 1

    print(f"{'case':8} {'seat':>4}  {'AkinoHana':>10}   " +
          "  ".join(f"{m.stem[:22]:>22}" for m in models))
    print("-" * (30 + 24 * len(models)))

    totals = {m: [0, 0] for m in models}
    for c in cases:
        row = [f"{c['tag']:8} {c['tw']:>4}  {c['base_pct']:>9.1f}%"]
        for m in models:
            tag_suffix = m.stem[:30]
            r = review_one(m, c, tag_suffix)
            if "error" in r:
                row.append(f"{'ERR:' + r['error'][:18]:>22}")
                continue
            mm, tt = r["matches"], r["total"]
            if tt:
                pct = 100.0 * mm / tt
                totals[m][0] += mm
                totals[m][1] += tt
                flag = "" if abs(tt - c["base_total"]) <= 2 else f"(!{tt})"
                row.append(f"{pct:>20.1f}%{flag}")
            else:
                row.append(f"{'no data':>22}")
        print("  ".join(row))

    print("-" * (30 + 24 * len(models)))
    base_m = sum(c["base_matches"] for c in cases)
    base_t = sum(c["base_total"] for c in cases)
    print(f"{'TOTAL':8} {'':>4}  {100.0 * base_m / base_t:>9.1f}%   " +
          "  ".join(
              (f"{100.0 * v[0] / v[1]:>21.1f}%" if v[1] else f"{'n/a':>22}")
              for v in (totals[m] for m in models)
          ))
    print(f"\nAkino Hana baseline: {base_m}/{base_t} = {100.0 * base_m / base_t:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
