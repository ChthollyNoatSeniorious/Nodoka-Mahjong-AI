#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recon: how does the hall-of-fame submit box actually work, and does
submitting a game for RIGEL 1.4 cost credits?

The model dropdown is the critical clue:

    zenith_10   天極 ZENITH 1.0 (名人堂免費)
    comet_10    彗影 COMET 1.0 (實驗) (名人堂免費)
    nova_10     新星 NOVA 1.0 (名人堂免費)
    halo_11     星環 HALO 1.1 (名人堂免費)
    rigel_14    長明 RIGEL 1.4          <-- NO free label
    rigel_13    長明 RIGEL 1.3
    rigel_12    長明 RIGEL 1.2
    halo_10     星環 HALO 1.0
    mjai_41b    參考引擎 4.1b (名人堂免費)
    rigel_10    長明 RIGEL 1.0 (免費)

Only some engines are advertised as free, and rigel_14 is not one of them.
So this script does NOT submit anything.  It only:
  1. reads the current credit balance,
  2. looks for a submit endpoint that is distinct from the paid POST /review,
  3. fetches the page/JS to see which endpoint the form posts to.

Nothing here spends credits.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = "https://review.bigcoach.work"
API = BASE + "/api/v2"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def req(url, method="GET", body=None, accept="application/json"):
    data = None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": accept,
        "Cookie": COOKIE,
        "Referer": BASE + "/hall-of-fame",
    }
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


if not COOKIE:
    print("set BIGCOACH_COOKIE first")
    sys.exit(2)

print("=" * 70)
print("1. CURRENT CREDIT BALANCE (before anything)")
print("=" * 70)
st, txt = req(API + "/membership/status")
print(f"HTTP {st}")
if st == 200:
    try:
        d = json.loads(txt).get("data", json.loads(txt))
        for k in ("tier", "monthlyLimit", "usedCredits", "creditBalance",
                  "credits", "resetAt", "periodEnd"):
            if k in d:
                print(f"   {k} = {d[k]}")
        print("   full:", json.dumps(d, ensure_ascii=False)[:600])
    except Exception as e:
        print("   parse:", e, txt[:300])
else:
    print(txt[:300])
print()

print("=" * 70)
print("2. LOOK FOR A SUBMIT ENDPOINT SEPARATE FROM POST /review")
print("=" * 70)
candidates = [
    "/hall-of-fame/review", "/hall-of-fame/submit", "/hall-of-fame/run",
    "/hall-of-fame/analyze", "/hall-of-fame/paipu", "/hall-of-fame/queue",
    "/tasks", "/tasks/submit", "/review/hall-of-fame",
]
for c in candidates:
    st, txt = req(API + c, method="GET")
    note = ""
    if st == 200:
        note = " <-- EXISTS (GET)"
    elif st == 405:
        note = " <-- exists but needs POST"
    elif st == 401:
        note = " auth"
    print(f"   GET  {c:34} -> {st}{note}")
print()

print("=" * 70)
print("3. WHAT DOES THE PAGE ITSELF CALL?")
print("=" * 70)
st, html = req(BASE + "/hall-of-fame", accept="text/html")
print(f"page HTTP {st}, {len(html)} bytes")
if st == 200:
    # find script bundles
    srcs = re.findall(r'src="([^"]+\.js[^"]*)"', html)
    print(f"   script bundles: {len(srcs)}")
    for s in srcs[:10]:
        print("     ", s)
    # endpoints mentioned inline
    eps = set(re.findall(r'/api/v2/[A-Za-z0-9_\-/{}]+', html))
    print(f"   inline /api/v2 paths: {sorted(eps)[:20]}")
    if "hof-submit-paipu" in html:
        print("   found #hof-submit-paipu")
    if "hof-submit-model-4p" in html:
        print("   found #hof-submit-model-4p")
print()
print("NOTE: nothing was submitted; no credits were spent.")
