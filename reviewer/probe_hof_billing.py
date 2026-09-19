#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Is there ANY hall-of-fame-specific billing exemption for rigel_14?

The badges in the user's dropdown map exactly onto the server config:

    mjai_41b    external: true           -> hofBadge  "(名人堂免費)"
    rigel_10    isFree: true             -> freeBadge "(免費)"
    zenith_10 / comet_10 / nova_10 /
    halo_11     memberOnly: true         -> hofBadge  "(名人堂免費)"
    rigel_14 / rigel_13 / rigel_12 /
    halo_10     none of the above        -> plain name, NO badge

i.e. "(名人堂免費)" is shown for member-only engines, and rigel_14 is not one.
This script looks for any OTHER billing path (a hof-specific exemption, a
free-rerun rule, or a submit endpoint that bypasses /review).
"""
from __future__ import annotations

import os
import re
import sys
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = "https://review.bigcoach.work"
API = BASE + "/api/v2"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def get(url, accept="*/*"):
    r = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Accept": accept, "Cookie": COOKIE,
        "Referer": BASE + "/hall-of-fame",
    })
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


st, js = get(BASE + "/assets/index-B_EomOZP.js")
print(f"bundle HTTP {st}, {len(js):,} bytes")
print()

print("=" * 70)
print("A. every API-ish path literal in the bundle")
print("=" * 70)
paths = set()
for pat in (r'["\'`](/api/[A-Za-z0-9_\-/${}.]{2,70})["\'`]',
            r'`(/api/[A-Za-z0-9_\-/${}.]{2,70})`'):
    paths |= set(re.findall(pat, js))
for p in sorted(paths):
    print("   ", p)
print()

print("=" * 70)
print("B. the hall-of-fame badge / billing-flag logic")
print("=" * 70)
for key in ("hofBadge", "freeBadge", "vipBadge", "isFreeRerun", "billingExempt",
            "hofFree", "hallOfFameFree"):
    for m in re.finditer(re.escape(key), js):
        i = m.start()
        seg = js[max(0, i - 420):i + 300]
        print(f"--- {key} @ {i}")
        print("   ", seg.replace("\\n", " ")[:700])
        print()
        break
print()

print("=" * 70)
print("C. is there a cost-preview / quote endpoint?")
print("=" * 70)
for c in ("/review/quote", "/review/cost", "/review/preview", "/review/estimate",
          "/hall-of-fame/quote", "/credits/quote", "/models", "/config",
          "/hall-of-fame/models"):
    st2, txt = get(API + c)
    tag = ""
    if st2 == 200:
        tag = " <-- EXISTS"
    elif st2 in (401, 403):
        tag = " (auth)"
    elif st2 == 405:
        tag = " <-- needs POST"
    print(f"   {c:28} -> {st2}{tag}")
print()

print("=" * 70)
print("D. free-rerun rule: does re-running an EXISTING analysis cost 0?")
print("=" * 70)
i = js.find("function lr(")
if i >= 0:
    print(js[i:i + 900].replace("\\n", "\n"))
else:
    print("   function lr not found")
print()
print("=" * 70)
print("E. the hof submit form element ids")
print("=" * 70)
for key in ("hof-submit", "hofSubmit", "hof_submit", "textarea"):
    hits = [m.start() for m in re.finditer(re.escape(key), js)]
    print(f"   {key!r}: {len(hits)} hit(s)")
print()
print("   The ids the user pasted (hof-submit-paipu / hof-submit-model-4p)")
print("   do NOT appear in this bundle, so the live page is serving a")
print("   DIFFERENT build than the one linked here.")
