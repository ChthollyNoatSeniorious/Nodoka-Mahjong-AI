#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final bigcoach-run report:
  * coverage of the 500-paipu list (taskId presence per paipu, per player)
  * deliverable counts: fetched reviews, converted games, distill growth
  * writes reviewer/out/bigcoach_run_report.md
"""
from __future__ import annotations

import glob
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
OUT = HERE / "out"
RUNS = OUT / "bigcoach_runs"
PAIPU_RE = re.compile(r"paipu=([A-Za-z0-9_.-]+)")
PAIPU_TXT = OUT / "player72520_paipus.txt"


def main() -> int:
    paipu_meta = []
    for line in PAIPU_TXT.read_text(encoding="utf-8").splitlines():
        m = PAIPU_RE.search(line)
        if m:
            name = line.split("|")[0].strip()
            paipu_meta.append((m.group(1), name))
    all_paipus = {p for p, _ in paipu_meta}

    # taskId records from every state file
    recs = []
    for f in sorted(glob.glob(str(RUNS / "_state*.json"))):
        try:
            d = json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        recs += d.get("results", [])
    by_paipu = {}
    for r in recs:
        p = r.get("paipu")
        if p and r.get("taskId"):
            by_paipu.setdefault(p, []).append(r)

    covered = set(by_paipu)
    missing = sorted(all_paipus - covered, key=lambda p: next(
        i for i, (pp, _) in enumerate(paipu_meta) if pp == p))
    # what failed last for missing ones (from state failure records)
    fail_by_paipu = {}
    for r in recs:
        p = r.get("paipu")
        if p and not r.get("taskId"):
            fail_by_paipu[p] = r.get("detail") or r.get("status") or ""

    n_taskids = len({r["taskId"] for r in recs if r.get("taskId")})
    fetched = sorted(p.stem for p in (OUT / "api_runs").glob("*.meta.json"))
    conv_html = sorted(p.stem for p in (OUT / "html_runs").glob("*.json"))

    from collections import Counter
    by_player = Counter()
    for p, name in paipu_meta:
        if p in covered:
            by_player[name] += 1
    miss_player = Counter()
    for p, name in paipu_meta:
        if p in missing:
            miss_player[name] += 1

    lines = []
    A = lines.append
    A("# bigcoach RIGEL 1.4 run report (player 72520 玉南 mode=12)")
    A("")
    A(f"- paipu list        : {len(all_paipus)}  ({PAIPU_TXT.name})")
    A(f"- paipus covered    : {len(covered)}  ({100.0*len(covered)/len(all_paipus):.1f}%)")
    A(f"- paipus missing    : {len(missing)}")
    A(f"- recorded taskIds  : {n_taskids} (unique)")
    A(f"- fetched reviews   : {len(fetched)} (api_runs)")
    A(f"- converted games   : {len(conv_html)} (html_runs)")
    A("")
    A("## coverage by player")
    A("")
    A("| player | covered | missing | total |")
    A("|---|---|---|---|")
    tot_by_player = Counter(name for _, name in paipu_meta)
    for name in sorted(tot_by_player):
        A(f"| {name} | {by_player.get(name, 0)} | "
          f"{miss_player.get(name, 0)} | {tot_by_player[name]} |")
    A("")
    A("## missing paipus")
    A("")
    if missing:
        for p in missing:
            why = fail_by_paipu.get(p, "")
            nm = next(name for pp, name in paipu_meta if pp == p)
            A(f"- {nm} | `{p}` | {why[:60]}")
    else:
        A("(none)")
    A("")
    A(f"- note: recovered via cached resubmission: "
      f"{sum(1 for r in recs if r.get('note') == 'topup')} paipus")
    A(f"- hard-failure recap (last recorded submit error):")
    from collections import Counter as C2
    errs = C2()
    for p in missing:
        why = fail_by_paipu.get(p, "")
        errs["INVALID_PAIPU" if "INVALID" in why else
             ("503" if "503" in why else
              ("402" if "402" in why else why[:30]))] += 1
    for k, v in errs.most_common():
        A(f"  - {v}x {k}")

    report = "\n".join(lines)
    (OUT / "bigcoach_run_report.md").write_text(
        report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())