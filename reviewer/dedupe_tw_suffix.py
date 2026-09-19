#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deduplicate hof_free files whose gids differ only by the &tw=<seat> suffix.

The account history can carry paipu URLs like https://tenhou.net/3/?log=X&tw=0
so a game may end up saved as both "X&tw=0.json" and the canonical "X.json".
Keep the canonical file (no tw suffix); drop the other; fix the index.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

OUT = pathlib.Path("reviewer/out/hof_free")
IDX = OUT / "_index.json"


def canon(gid: str) -> str:
    return re.sub(r"&tw=\d+$", "", gid)


def main() -> int:
    index = json.loads(IDX.read_text(encoding="utf-8"))
    files = {f.name[:-5] for f in OUT.glob("*.json") if f.name != "_index.json"}
    dropped = 0
    for gid in sorted(files):
        c = canon(gid)
        if c == gid:
            continue
        rec = index.pop(gid, None)
        if (OUT / f"{c}.json").is_file():
            (OUT / f"{gid}.json").unlink(missing_ok=True)
            dropped += 1
            print(f"drop  {gid}.json          (canonical {c}.json kept)")
        else:
            (OUT / f"{gid}.json").rename(OUT / f"{c}.json")
            if rec:
                index[c] = rec
            print(f"rename {gid}.json -> {c}.json")
    print(f"\ndropped {dropped}; files now: "
          f"{len(list(OUT.glob('*.json'))) - 1}; index: {len(index)}")
    IDX.write_text(json.dumps(index, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())