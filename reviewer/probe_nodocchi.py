#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Can we list a hall-of-fame player's Tenhou games from nodocchi.moe?

nodocchi is a hash-routed SPA, so the game list comes from an API, not the HTML.
This finds that API and pulls the paipu ids for one player so they can be
submitted to the hall-of-fame page.

Read-only.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def get(url, accept="*/*", referer="https://nodocchi.moe/"):
    r = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": accept, "Referer": referer,
        "Accept-Language": "ja,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


NAME = "☆孫燕姿☆"
print("=" * 72)
print(f"nodocchi recon for {NAME}")
print("=" * 72)

st, html = get("https://nodocchi.moe/tenhoulog/", "text/html")
print(f"page HTTP {st}, {len(html)} bytes")
if st == 200:
    srcs = set(re.findall(r'<script[^>]+src="([^"]+)"', html))
    print("scripts:")
    for s in sorted(srcs):
        print("   ", s)
    print()
    # the SPA usually embeds its API paths in the bundle
    for s in sorted(srcs):
        u = s if s.startswith("http") else "https://nodocchi.moe" + (
            s if s.startswith("/") else "/" + s)
        if not u.endswith(".js"):
            continue
        st2, js = get(u)
        if st2 != 200:
            print(f"   {s} -> HTTP {st2}")
            continue
        eps = sorted(set(re.findall(
            r'["\'`]([a-z0-9_\-/\.]*(?:json|api|log|cgi)[a-z0-9_\-/\.]*)["\'`]',
            js, re.I)))
        print(f"   {s}: {len(js):,} bytes, {len(eps)} endpoint-ish literals")
        for e in eps[:25]:
            print("        ", e)
        for kw in ("tenhoulog", "getlist", "player", "search"):
            if kw in js:
                i = js.find(kw)
                print(f"        [{kw}] ...{js[max(0,i-120):i+160]}...")
        print()

print("=" * 72)
print("try the known nodocchi endpoints")
print("=" * 72)
q = urllib.parse.quote(NAME)
cands = [
    f"https://nodocchi.moe/api/listuser.php?name={q}",
    f"https://nodocchi.moe/api/getlist.php?name={q}",
    f"https://nodocchi.moe/tenhoulog/api/list?name={q}",
    f"https://nodocchi.moe/api/player.php?name={q}",
    f"https://nodocchi.moe/api/searchplayer.php?name={q}",
]
for c in cands:
    st, txt = get(c)
    print(f"   {c[:78]:78} -> {st} ({len(txt)} b)")
    if st == 200 and txt.strip():
        print("      ", txt[:300].replace("\n", " "))
