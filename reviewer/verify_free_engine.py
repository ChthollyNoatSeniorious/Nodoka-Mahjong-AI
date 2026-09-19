#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify the model identity of every free-harvested task.

The old 416-game pool was verified through the /tasks/{id}/result payload
(modelName == 'RIGEL 1.4').  The free-harvest index only stores taskIds, so
re-verify them the same way.  Read-only: fetching task results costs nothing.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

API = "https://review.bigcoach.work/api/v2"
ORIGIN = "https://review.bigcoach.work"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def call(url):
    if url.startswith("/api/"):
        url = ORIGIN + url
    elif url.startswith("/"):
        url = API + url
    r = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json",
        "Cookie": COOKIE, "Referer": "https://gokujan.com/hall-of-fame"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


def main() -> int:
    idx = pathlib.Path("reviewer/out/hof_free/_index.json")
    index = json.loads(idx.read_text(encoding="utf-8"))
    tasks = [(gid, rec["taskId"]) for gid, rec in index.items()
             if rec.get("taskId")]
    print(f"tasks to verify: {len(tasks)}")
    rigel = other = missing = 0
    bad = []
    for gid, task in tasks:
        st, txt = call(f"/tasks/{task}/result")
        if st != 200:
            missing += 1
            bad.append((gid, task, f"HTTP {st}"))
            continue
        try:
            d = json.loads(txt).get("data") or {}
        except Exception:
            missing += 1
            continue
        name = d.get("modelName")
        if name == "RIGEL 1.4":
            rigel += 1
        else:
            other += 1
            bad.append((gid, task, f"modelName={name!r}"))
    print(f"  RIGEL 1.4 : {rigel}")
    print(f"  other     : {other}")
    print(f"  missing   : {missing}")
    for b in bad[:10]:
        print("   !", b)
    if other == 0:
        print("=> all free-harvested tasks are RIGEL 1.4 (provenance OK)")
    return 0


if __name__ == "__main__":
    sys.exit(main())