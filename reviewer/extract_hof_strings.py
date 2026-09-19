#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract the hof.submitPanel.* UI strings (they may reveal the run limit)."""
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
r = urllib.request.Request("https://gokujan.com/assets/locales-LRQV2N5c.js",
                           headers={"User-Agent": "Mozilla/5.0", "Cookie": COOKIE})
js = urllib.request.urlopen(r, timeout=60).read().decode("utf-8", "replace")

# The bundle is a JS object; find the section for zh-TW and extract the keys.
# Keys appear as "hof.submitPanel.xxx":"value" possibly with unicode escapes.
for key in ("hof.submitPanel.dailyExceeded", "hof.submitPanel.successCached",
            "hof.submitPanel.intro", "hof.submitPanel.disabled",
            "hof.submitPanel.suspendedHint", "hof.submitPanel.strikeWarning",
            "hof.submitPanel.notAPlayerGame", "hof.submitPanel.paipuLabel",
            "hof.submitPanel.title"):
    found = False
    for pat in (re.escape(key) + r'"\s*:\s*"((?:[^"\\]|\\.){1,300})"',
                re.escape(key) + r'\s*:\s*\{[^}]*"zh-TW"\s*:\s*"((?:[^"\\]|\\.){1,300})"'):
        for m in re.finditer(pat, js):
            v = m.group(1)
            try:
                v = v.encode().decode("unicode_escape")
            except Exception:
                pass
            print(f"{key:36} = {v[:200]}")
            found = True
            break
        if found:
            break
    if not found:
        # fall back: any context window around the key
        i = js.find(key)
        if i >= 0:
            seg = js[i:i + 200]
            print(f"{key:36} = (raw) {seg[:180]}")
        else:
            print(f"{key:36} = NOT FOUND")