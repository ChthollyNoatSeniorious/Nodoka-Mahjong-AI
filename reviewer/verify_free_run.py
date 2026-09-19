#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify the newly created hall-of-fame analysis is really RIGEL 1.4 and
contains the per-move pi weights we need for training.

taskId from the free submit test: d6c36f8c4e834cd9
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

API = "https://review.bigcoach.work/api/v2"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")
TASK = "d6c36f8c4e834cd9"


ORIGIN = "https://review.bigcoach.work"


def get(url, accept="application/json"):
    # Two kinds of path come through here:
    #   "/tasks/..."              -> needs the /api/v2 prefix
    #   "/api/v2/tasks/...?token" -> already complete, needs only the origin
    if url.startswith("/api/"):
        url = ORIGIN + url
    elif url.startswith("/"):
        url = API + url
    r = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Accept": accept, "Cookie": COOKIE,
        "Referer": "https://gokujan.com/hall-of-fame"})
    try:
        with urllib.request.urlopen(r, timeout=90) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


print(f"task {TASK}")
for attempt in range(12):
    st, txt = get(f"/tasks/{TASK}/result")
    if st != 200:
        print(f"  attempt {attempt+1}: HTTP {st} {txt[:200]}")
        time.sleep(5)
        continue
    d = json.loads(txt).get("data") or {}
    url = d.get("jsonUrl")
    print(f"  engine   : {d.get('modelName')!r} / {d.get('modelEngineKeys')!r}")
    print(f"  mode     : {d.get('analysisMode')!r}   ui: {d.get('ui')!r}")
    print(f"  jsonUrl  : {str(url)[:110]}")
    if not url:
        print("  not ready yet; waiting")
        time.sleep(8)
        continue
    st2, body = get(url)
    if st2 != 200:
        print(f"  data HTTP {st2}")
        time.sleep(5)
        continue
    rev = json.loads(body)
    rv = rev.get("review", {})
    print()
    print("  === review payload ===")
    for k in ("modelName", "temperature", "nplayer", "total_matches",
              "total_reviewed"):
        if k in rv:
            print(f"     {k:16} = {rv[k]!r}")
    kyokus = rv.get("kyokus") or []
    print(f"     kyokus           = {len(kyokus)}")
    n_entries = sum(len(k.get("entries") or []) for k in kyokus)
    print(f"     entries          = {n_entries}")
    if kyokus:
        e = (kyokus[0].get("entries") or [{}])[0]
        print(f"     entry keys       = {sorted(e.keys())}")
        det = e.get("details") or []
        print(f"     details on first = {len(det)}")
        if det:
            print("        sample:", json.dumps(det[0], ensure_ascii=False)[:220])
        s = sum(x.get("prob", 0) for x in det)
        print(f"     prob sum         = {s:.6f}")
        print(f"     expected         = {e.get('expected')}")
        print(f"     actual           = {e.get('actual')}")
    has_log = "mjai_log" in rev
    print(f"     has mjai_log     = {has_log}")
    print()
    print("  => OK, usable for distillation" if n_entries else "  => empty")
    break
