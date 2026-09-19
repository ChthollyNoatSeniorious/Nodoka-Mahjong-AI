#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Measure the hall-of-fame submit rate limit, and verify what we already got.

Findings so far:
  * POST /hall-of-fame/submit with rigel_14 is FREE (balance unchanged, a new
    analysis was created)
  * ☆孫燕姿☆ alone has 3,183 four-player games on nodocchi
  * but after ~2 submissions the server returned 275 consecutive HTTP 429
    RATE_LIMITED

So the whole plan depends on the sustainable rate.  This:
  1. waits out the cooldown,
  2. reads the rate-limit response headers (Retry-After / X-RateLimit-*),
  3. verifies the two reviews already downloaded.
"""
from __future__ import annotations

import json
import os
import pathlib
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


def request(url, body=None, method="GET"):
    if url.startswith("/api/"):
        url = ORIGIN + url
    elif url.startswith("/"):
        url = API + url
    data = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
         "Cookie": COOKIE, "Referer": "https://gokujan.com/hall-of-fame",
         "Origin": "https://gokujan.com"}
    if data:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, {}, str(e)


print("=" * 72)
print("1. verify the two reviews already downloaded (they were FREE)")
print("=" * 72)
d = pathlib.Path("reviewer/out/hof_free")
for f in sorted(d.glob("*.json")):
    try:
        rev = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"   {f.name}: unreadable ({e})")
        continue
    rv = rev.get("review", {})
    kyo = rv.get("kyokus") or []
    ents = sum(len(k.get("entries") or []) for k in kyo)
    ok = 0
    tot = 0
    for k in kyo:
        for e in k.get("entries") or []:
            det = e.get("details") or []
            if det:
                tot += 1
                if abs(sum(x.get("prob", 0) for x in det) - 1.0) < 1e-4:
                    ok += 1
    print(f"   {f.name}")
    print(f"      model={rv.get('modelName')!r} kyokus={len(kyo)} entries={ents}")
    print(f"      prob sums == 1 : {ok}/{tot}")
    print(f"      mjai_log: {'mjai_log' in rev}")
print()

print("=" * 72)
print("2. rate-limit headers (waiting 60s first to be polite)")
print("=" * 72)
time.sleep(60)
st, hdrs, txt = request("/hall-of-fame/submit", {
    "paipu": "https://tenhou.net/3/?log=2020100913gm-0041-0000-388c8bcb",
    "model": "rigel_14", "analysisMode": "standard", "language": "zh-TW"},
    method="POST")
print(f"   HTTP {st}")
interesting = {k: v for k, v in hdrs.items()
               if any(t in k.lower() for t in
                      ("rate", "retry", "limit", "remain", "reset", "after"))}
if interesting:
    for k, v in interesting.items():
        print(f"      {k}: {v}")
else:
    print("      (no rate-limit headers exposed)")
print(f"   body: {txt[:220]}")
print()
print("   note: this re-submitted a game we ALREADY analysed, so the server")
print("   should answer cached=true and no analysis is re-run.")
