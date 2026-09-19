#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Map the four target players' paipus to fetched taskIds.

Reads out/player72520_paipus.txt (player|time|paipu url), joins against
out/bigcoach_runs/_state.json results (paipu -> taskId), and writes one taskId
list per player into out/html_players/, plus _all_players.txt.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
PAIPU_RE = re.compile(r"paipu=([A-Za-z0-9_.-]+)")

players: dict[str, list[str]] = {}
for line in (HERE / "out" / "player72520_paipus.txt").read_text(encoding="utf-8").splitlines():
    if not line or line.startswith("#"):
        continue
    parts = line.split("|")
    if len(parts) < 2:
        continue
    m = PAIPU_RE.search(line)
    if not m:
        continue
    players.setdefault(parts[0].strip(), []).append(m.group(1))

state = json.loads((HERE / "out" / "bigcoach_runs" / "_state.json").read_text(encoding="utf-8"))
paipu2task = {r.get("paipu"): r.get("taskId") for r in state["results"] if r.get("taskId")}

outdir = HERE / "out" / "html_players"
outdir.mkdir(exist_ok=True)
all_ids: list[str] = []
for name, paipus in players.items():
    ids = [paipu2task[p] for p in paipus if p in paipu2task]
    ids = list(dict.fromkeys(ids))
    all_ids.extend(ids)
    f = outdir / f"{name}.txt"
    f.write_text("\n".join(ids) + "\n", encoding="utf-8")
    print(f"{name}: {len(paipus)} paipus -> {len(ids)} taskIds -> {f.name}", flush=True)

(outdir / "_all_players.txt").write_text("\n".join(dict.fromkeys(all_ids)) + "\n", encoding="utf-8")
print(f"total unique taskIds: {len(dict.fromkeys(all_ids))}")