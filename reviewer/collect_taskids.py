#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect every taskId recorded in bigcoach_runs state files into
out/_txt_ids.txt (dedup, sorted) for fetch_api_reviews.py."""
from __future__ import annotations

import glob
import json
import pathlib
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
RUNS = HERE / "out" / "bigcoach_runs"
OUT = HERE / "out" / "_txt_ids.txt"


def main() -> int:
    ids = []
    for f in sorted(glob.glob(str(RUNS / "_state*.json"))):
        try:
            d = json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
        except Exception as e:
            print(f"skip {f}: {e}")
            continue
        n = 0
        for r in d.get("results", []):
            tid = r.get("taskId")
            if tid:
                ids.append(tid)
                n += 1
        print(f"{pathlib.Path(f).name}: {n} taskIds")
    ids = sorted(set(ids))
    OUT.write_text("\n".join(ids) + ("\n" if ids else ""), encoding="utf-8")
    print(f"total unique taskIds: {len(ids)} -> {OUT}")
    # cross-check against already fetched (.stem of x.meta.json is x.meta, so strip explicitly)
    fetched = sorted(p.name[: -len(".meta.json")]
                     for p in (HERE / "out" / "api_runs").glob("*.meta.json"))
    missing = [i for i in ids if i not in set(fetched)]
    print(f"already fetched: {len(fetched)}, still to fetch: {len(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())