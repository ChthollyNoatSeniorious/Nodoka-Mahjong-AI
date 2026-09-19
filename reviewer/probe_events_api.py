#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe candidate API endpoints for gokujan events listing."""
import json
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
ORIGIN = "https://review.bigcoach.work/api/v2"
GOKU = "https://gokujan.com"

CANDIDATES = [
    "/events/69289369",
    "/events/69289369/games",
    "/events/69289369/games?page=1",
    "/events/69289369?page=1",
    "/hall-of-fame/events/69289369",
    "/hall-of-fame/events/69289369/games?page=1",
    "/event/69289369",
    "/events/69289369/reviews",
]
for path in CANDIDATES:
    for base, name in ((ORIGIN, "bigcoach"), (GOKU, "gokujan")):
        url = base + path
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Accept": "application/json",
                                                   "Referer": "https://gokujan.com/events/69289369"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", "replace")
            print(f"[{name}] {path} -> HTTP {resp.status} len={len(body)} preview={body[:120]!r}")
        except urllib.error.HTTPError as e:
            print(f"[{name}] {path} -> HTTP {e.code}")
        except Exception as e:
            print(f"[{name}] {path} -> ERR {e}")