#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The submit form is probably on gokujan.com, not review.bigcoach.work.

Evidence:
  * /hall-of-fame links to https://gokujan.com/hall-of-fame
  * the pasted form uses DaisyUI class names (textarea-bordered, btn-primary,
    select-bordered), while the review.bigcoach bundle uses hashed CSS modules
  * the pasted ids (hof-submit-paipu, hof-submit-model-4p) appear in NO bundle
    served by review.bigcoach.work

So the hall-of-fame submit lives in a separate app.  Find its bundle and look
for the one billing flag that would make this free:

    if(!i || o || e.free || e.showcaseFree) return ft();   // zero cost

Read-only; spends nothing.
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
SITES = ["https://gokujan.com/hall-of-fame", "https://gokujan.com/"]


def get(url, accept="*/*", referer=None):
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
         "Accept": accept, "Cookie": COOKIE}
    if referer:
        h["Referer"] = referer
    r = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


alljs = []
for url in SITES:
    st, html = get(url, "text/html")
    print(f"=== {url} -> HTTP {st}, {len(html)} bytes ===")
    print(f"    hof-submit-paipu: {html.count('hof-submit-paipu')}   "
          f"hof-submit-model-4p: {html.count('hof-submit-model-4p')}   "
          f"rigel_14: {html.count('rigel_14')}")
    refs = set()
    for pat in (r'<script[^>]+src="([^"]+)"', r'<link[^>]+href="([^"]+)"'):
        refs |= set(re.findall(pat, html))
    js = [r for r in refs if ".js" in r]
    print("    js refs:", sorted(js)[:12])
    for r in js:
        u = r if r.startswith("http") else url.split("/hall-of-fame")[0].rstrip("/") + (
            r if r.startswith("/") else "/" + r)
        alljs.append(u)
    print()

alljs = sorted(set(alljs))
print(f"fetching {len(alljs)} script(s)")
print()
for u in alljs:
    st, js = get(u, "application/javascript")
    if st != 200:
        print(f"   {u} -> HTTP {st} ({len(js)} bytes)")
        continue
    tags = []
    if "hof-submit-paipu" in js:
        tags.append("HAS-FORM")
    if "showcaseFree" in js:
        tags.append("showcaseFree")
    if "hall-of-fame" in js:
        tags.append("hof")
    print(f"   {u.split('/')[-1]:40} {len(js):>9,} bytes  {' '.join(tags)}")

    if "hof-submit-paipu" in js or "showcaseFree" in js:
        print()
        for key in ("hof-submit-paipu", "showcaseFree"):
            for m in re.finditer(re.escape(key), js):
                i = m.start()
                print(f"   --- {key} @ {i} ---")
                print("   ", js[max(0, i - 1600):i + 1200].replace("\n", " ")[:2800])
                print()
                break
        # endpoint hints
        eps = sorted(set(re.findall(r'["\'`](/[a-z0-9\-/_]{3,60})["\'`]', js)))
        api = [e for e in eps if any(k in e for k in
               ("api", "hof", "review", "task", "submit", "hall"))]
        print("   endpoint-ish literals:", api[:40])
        print()
