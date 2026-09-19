#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract event taskIds, diff against fetched, spot-check a few via
the public read API (modelName/nplayer)."""
import json
import pathlib
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"

ev = json.loads((OUT / "_event_69289369.json").read_text(encoding="utf-8"))
ids = []
for g in ev["items"]:
    for s in g.get("seats") or []:
        if s.get("taskId"):
            ids.append((s["taskId"], s.get("nickname", ""), g["uuid"]))
ids.sort()
uniq = set(t for t, _, _ in ids)
print("total seat-entries:", len(ids), "unique taskIds:", len(uniq))

# diff against api_runs
runs = OUT / "api_runs"
fetched = {p.name[: -len(".meta.json")] for p in runs.glob("*.meta.json")}
new_ids = [t for t in uniq if t not in fetched]
print("already fetched:", len(uniq - set(new_ids)), "new:", len(new_ids))

(OUT / "_event_taskids.txt").write_text("\n".join(
    f"{t} {n} {u}" for t, n, u in ids) + "\n", encoding="utf-8")
(OUT / "_event_taskids_new.txt").write_text("\n".join(new_ids) + "\n",
                                            encoding="utf-8")
print("wrote _event_taskids.txt (all) and _event_taskids_new.txt (new only)")