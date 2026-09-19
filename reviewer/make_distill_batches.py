#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Split html_runs ids into per-batch .cmd files for html_to_distill merge."""
import glob
import io
import os

ids = sorted(os.path.basename(f)[:-5] for f in glob.glob("out/html_runs/*.json")
              if not os.path.basename(f).startswith("_"))
batch = 220
for b in range(0, len(ids), batch):
    chunk = ids[b:b + batch]
    cmd = '"..\\mortal\\.venv\\Scripts\\python.exe" -u html_to_distill.py ' + \
          " ".join("--gid " + i for i in chunk)
    with io.open(f"out/_distill_batch_{b // batch}.cmd", "w",
                 encoding="utf-8", newline="\n") as fh:
        fh.write(cmd + "\n")
print("ok", len(ids), "batches:", (len(ids) + batch - 1) // batch)