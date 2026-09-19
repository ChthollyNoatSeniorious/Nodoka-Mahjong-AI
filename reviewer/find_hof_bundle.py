#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find the bundle that actually contains the hall-of-fame submit form.

The bundle linked from /hall-of-fame does NOT contain the element ids the user
pasted (hof-submit-paipu / hof-submit-model-4p), so the live page must serve a
newer build or load a separate chunk.  Locate it, then look for `showcaseFree` --
the one flag in the billing function that makes a submission cost zero:

    function Ou(e){ ... if(!i || o || e.free || e.showcaseFree) return ft(); }
                                              ^^^^^^^^^^^^^^^ zero cost

If the hall-of-fame submit sets showcaseFree, then submitting a game for
RIGEL 1.4 there is FREE, and the user's idea works.  Read-only.
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
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def get(url, accept="*/*"):
    r = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": accept, "Cookie": COOKIE, "Referer": BASE + "/hall-of-fame",
    })
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


st, html = get(BASE + "/hall-of-fame", "text/html")
print(f"/hall-of-fame -> HTTP {st}, {len(html)} bytes")
print()
print("=== all script/link refs in the page ===")
refs = set()
for pat in (r'<script[^>]+src="([^"]+)"', r'<link[^>]+href="([^"]+)"'):
    refs |= set(re.findall(pat, html))
for r in sorted(refs):
    print("   ", r)
print()

print("=== do the pasted ids appear in the page HTML? ===")
for k in ("hof-submit-paipu", "hof-submit-model-4p", "rigel_14", "提交並複盤"):
    print(f"   {k!r}: {html.count(k)}")
print()

print("=== does the page reference a different entry bundle? ===")
m = re.findall(r'/assets/[A-Za-z0-9_\-\.]+\.js', html)
print("   assets:", sorted(set(m)))
print()

# fetch every bundle we can find and search it
js_refs = [r for r in refs if r.endswith(".js") and r.startswith("/")]
if not js_refs:
    js_refs = sorted(set(m))
found_any = False
for ref in js_refs:
    st2, js = get(BASE + ref)
    if st2 != 200:
        print(f"   {ref} -> HTTP {st2}")
        continue
    has_form = "hof-submit-paipu" in js
    has_flag = "showcaseFree" in js
    print(f"   {ref}: {len(js):,} bytes  form={has_form}  showcaseFree={has_flag}")
    if has_form or has_flag:
        found_any = True
    if has_flag:
        for mm in re.finditer("showcaseFree", js):
            i = mm.start()
            print()
            print("   --- showcaseFree context ---")
            print("   ", js[max(0, i - 300):i + 200].replace("\n", " "))
        for mm in re.finditer(r'\bOu\(', js):
            i = mm.start()
            print()
            print("   --- Ou( call site ---")
            print("   ", js[max(0, i - 600):i + 300].replace("\n", " "))
    if has_form:
        i = js.find("hof-submit-paipu")
        print()
        print("   --- hof submit form context ---")
        print("   ", js[max(0, i - 1500):i + 1500].replace("\n", " "))

if not found_any:
    print()
    print("   Neither the form ids nor showcaseFree were found in any bundle")
    print("   linked from this page -- the live build differs.")
