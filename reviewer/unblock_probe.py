#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gentle single-shot probe: is the submit quota unblocked NOW?

After the last 429 at 21:05/21:20 we made ZERO further attempts (by design).
If the limiter is a sliding window, it should have cleared long ago; the
"daily cap" theory was never actually tested after 21:20.

This submits ONE game.  Outcomes:
  200 cached=true  -> quota fine, cached game
  200 cached=false -> QUOTA UNBLOCKED, we can resume harvesting
  429              -> still blocked; log retry-after, stop (no loop)
"""
from __future__ import annotations

import json
import os
import sys
import time
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
PAIPU = "https://tenhou.net/3/?log=2020100913gm-0041-0000-388c8bcb"  # our 1st test game


def main() -> int:
    import urllib.parse
    st_games = 0
    # pick an unseen game
    try:
        r = urllib.request.Request(
            "https://nodocchi.moe/api/listuser.php?name="
            + urllib.parse.quote("☆孫燕姿☆"),
            headers={"User-Agent": "Mozilla/5.0",
                     "Referer": "https://nodocchi.moe/tenhoulog/"})
        lst = json.loads(urllib.request.urlopen(r, timeout=90)
                         .read().decode("utf-8", "replace")).get("list") or []
        idx = json.loads(
            open("reviewer/out/hof_free/_index.json", encoding="utf-8").read())
        paipu = None
        for e in lst:
            if not isinstance(e, dict) or e.get("playernum") != 4:
                continue
            u = e.get("url")
            if u and u.split("log=")[-1] not in idx:
                paipu = u
                break
        if paipu:
            PAIPU = paipu
    except Exception as e:
        print("nodocchi pickup failed, using known game:", e)

    body = json.dumps({"paipu": PAIPU, "model": "rigel_14",
                       "analysisMode": "standard", "language": "zh-TW"}).encode()
    r = urllib.request.Request(API + "/hall-of-fame/submit", data=body,
                               method="POST",
                               headers={"User-Agent": "Mozilla/5.0",
                                        "Accept": "application/json",
                                        "Cookie": COOKIE,
                                        "Content-Type": "application/json",
                                        "Referer": "https://gokujan.com/hall-of-fame",
                                        "Origin": "https://gokujan.com"})
    t0 = time.time()
    ra = None
    try:
        with urllib.request.urlopen(r, timeout=90) as resp:
            txt = resp.read().decode("utf-8", "replace")
        st = resp.status
    except urllib.error.HTTPError as e:
        st = e.code
        txt = e.read().decode("utf-8", "replace")
        ra = e.headers.get("retry-after")
    except Exception as e:
        print("ERR", e)
        return 1
    dt = time.time() - t0
    print(f"HTTP {st} in {dt:.1f}s")
    print("body:", txt[:400])
    if st == 200:
        d = json.loads(txt).get("data") or {}
        print(f"RESULT: QUOTA UNBLOCKED  taskId={d.get('taskId')} "
              f"cached={d.get('cached')}")
        print("ACTION: resume batches now (gap >= 45s, stop on 2 consecutive 429s)")
    elif st == 429:
        print(f"RESULT: still blocked  retry-after={ra}s "
              f"({time.strftime('%H:%M', time.localtime(time.time()+float(ra)))} UTC)")
        print("ACTION: wait for the 00:35 scheduled test")
    return 0


if __name__ == "__main__":
    sys.exit(main())