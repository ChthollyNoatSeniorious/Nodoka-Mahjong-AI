#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Discover the bigcoach API endpoints from the site's own JavaScript.

The browser Network panel shows only the last path segment ("submit",
"progress", "result"), not the full URL.  The single-page app hard-codes those
paths in its bundle, so we download the bundle and grep for them.
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
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def get(url: str, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": accept, "Cookie": COOKIE,
        "Accept-Language": "zh-TW,zh;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


print("fetching index ...")
html = get(BASE + "/hall-of-fame", "text/html").decode("utf-8", "replace")
print(f"  html {len(html)} bytes")

scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
links = re.findall(r'<link[^>]+href="([^"]+\.js)"', html)
assets = []
for s in scripts + links:
    if s.startswith("http"):
        assets.append(s)
    elif s.startswith("/"):
        assets.append(BASE + s)
    else:
        assets.append(BASE + "/" + s)
print(f"  found {len(assets)} asset(s)")

paths = set()
for a in assets:
    try:
        js = get(a).decode("utf-8", "replace")
    except Exception as exc:
        print(f"  !! {a}: {exc}")
        continue
    print(f"  scanned {a.split('/')[-1]} ({len(js)} bytes)")
    # absolute api paths
    for m in re.findall(r'["\'`](/api/[A-Za-z0-9_\-/{}$.:]+)["\'`]', js):
        paths.add(m)
    # template-built paths
    for m in re.findall(r'["\'`](/api/v\d/[A-Za-z0-9_\-/]*)["\'`]', js):
        paths.add(m)

print()
print("=== /api paths found in the bundle ===")
for p in sorted(paths):
    print("  ", p)
print()
# also look for the bare words from the network log
for word in ("submit", "progress", "result", "classic"):
    hits = sorted({p for p in paths if word in p.lower()})
    print(f"  containing {word!r}: {hits}")
