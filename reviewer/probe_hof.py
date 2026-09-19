#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enumerate the hall of fame: players and their already-analysed games.

Endpoints (from the SPA bundle):
    GET /hall-of-fame/players
    GET /hall-of-fame/players/{platform}/{name}
    GET /hall-of-fame/my-players

Each analysed run carries `engineKeys` (e.g. "rigel_14") so we can pick only
RIGEL 1.4 (長明 1.4) reviews and ignore other engines such as NOVA.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = "https://review.bigcoach.work/api/v2"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def get(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json", "Cookie": COOKIE,
        "Referer": "https://review.bigcoach.work/hall-of-fame"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace"), url
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), url


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--player", help="platform/name, e.g. tenhou/☆孫燕姿☆")
    ap.add_argument("--platform", default="tenhou")
    args = ap.parse_args()

    if args.player:
        plat, _, name = args.player.partition("/")
        for extra in ({}, {"a": 0}, {"page": 0}, {"limit": 50, "offset": 0}):
            st, txt, url = get(f"/hall-of-fame/players/{plat}/{urllib.parse.quote(name)}",
                               extra or None)
            print(f"===== GET {url} -> {st} =====")
            try:
                obj = json.loads(txt)
                print(json.dumps(obj, ensure_ascii=False, indent=1)[:3000])
            except Exception:
                print(txt[:600])
            print()
            if st == 200:
                break
        return 0

    st, txt, url = get("/hall-of-fame/players")
    print(f"===== GET {url} -> {st} =====")
    try:
        obj = json.loads(txt)
        d = obj.get("data") or obj
        if isinstance(d, list):
            print(f"list of {len(d)}")
            for it in d[:6]:
                print("  ", json.dumps(it, ensure_ascii=False)[:220])
        elif isinstance(d, dict):
            print("keys:", list(d.keys()))
            print(json.dumps(d, ensure_ascii=False, indent=1)[:2500])
    except Exception:
        print(txt[:900])
    print()

    st, txt, url = get("/hall-of-fame/my-players")
    print(f"===== GET {url} -> {st} =====")
    try:
        obj = json.loads(txt)
        print(json.dumps(obj, ensure_ascii=False, indent=1)[:1500])
    except Exception:
        print(txt[:600])
    return 0


if __name__ == "__main__":
    sys.exit(main())
