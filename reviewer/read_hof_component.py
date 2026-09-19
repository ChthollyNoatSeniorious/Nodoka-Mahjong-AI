#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read the /hall-of-fame page component to get the submit payload and see
whether it is billed.

Route table says:  {path:"/hall-of-fame", element: <S0/>}
So the form + submit payload live in the S0 component.  Read-only.
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

COOKIE = os.environ.get("BIGCOACH_COOKIE", "")
r = urllib.request.Request("https://gokujan.com/assets/index-B_EomOZP.js",
                           headers={"User-Agent": "Mozilla/5.0", "Cookie": COOKIE})
js = urllib.request.urlopen(r, timeout=60).read().decode("utf-8", "replace")

print("=" * 72)
print("where is S0 defined?")
print("=" * 72)
for pat in (r'function S0\(', r'\bS0\s*=', r'const S0', r'S0='):
    hits = [m.start() for m in re.finditer(pat, js)]
    print(f"   {pat!r}: {len(hits)} -> {hits[:5]}")
print()

idx = None
for pat in (r'function S0\(', r'\bS0\s*='):
    m = re.search(pat, js)
    if m:
        idx = m.start()
        break

if idx is None:
    print("S0 not found; searching for the hof submit usage instead")
    for m in re.finditer(r'j_', js):
        i = m.start()
        seg = js[max(0, i - 120):i + 200]
        if "mutationFn" in seg or "submit" in seg.lower():
            print("   *", seg.replace("\n", " ")[:320])
else:
    print("=" * 72)
    print("S0 component body (looking for the submit payload)")
    print("=" * 72)
    body = js[idx:idx + 9000]
    print(body.replace("\\n", "\n")[:9000])
