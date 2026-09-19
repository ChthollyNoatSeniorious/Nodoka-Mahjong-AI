#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find any endpoint that reports the hall-of-fame quota/status.

The SubmitPanel shows strike warnings with a live `remaining` count and the
daily-limit error, so the server likely exposes per-account hof state.  Search
the bundle for query keys / endpoints that serve it, then probe them.
Read-only.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ORIGIN = "https://review.bigcoach.work"
API = ORIGIN + "/api/v2"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def get_url(url):
    if url.startswith("/api/"):
        url = ORIGIN + url
    elif url.startswith("/"):
        url = API + url
    r = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json",
        "Cookie": COOKIE, "Referer": "https://gokujan.com/hall-of-fame"})
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


def main() -> int:
    r = urllib.request.Request(
        "https://gokujan.com/assets/index-B_EomOZP.js",
        headers={"User-Agent": "Mozilla/5.0", "Cookie": COOKIE})
    js = urllib.request.urlopen(r, timeout=60).read().decode("utf-8", "replace")

    print("=== query keys mentioning hof/quota/limit/status ===")
    keys = set()
    for m in re.finditer(r'queryKey:\s*\["([^"]+)"\]', js):
        k = m.group(1)
        if any(t in k.lower() for t in
               ("hof", "quota", "limit", "status", "strike", "run")):
            keys.add(k)
            i = m.start()
            print(f"   {k}")
            print("      ", js[max(0, i - 170):i + 130].replace("\n", " ")[:300])
    print()

    print("=== candidate endpoints to probe ===")
    cands = ["/hall-of-fame/status", "/hall-of-fame/quota",
             "/hall-of-fame/limits", "/hall-of-fame/strikes",
             "/hall-of-fame/state", "/hall-of-fame/me"]
    for c in cands:
        st, txt = get_url(c)
        print(f"   GET {c:26} -> {st}{'  ' + txt[:160] if st == 200 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())