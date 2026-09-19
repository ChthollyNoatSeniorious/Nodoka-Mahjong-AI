#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe gokujan review + events pages: save raw HTML for structure analysis."""
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
OUT = "reviewer/out/_probe"


def get(url, name):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            html = r.read().decode("utf-8", "replace")
        print(url, "len=", len(html))
        open(f"{OUT}_{name}.html", "w", encoding="utf-8").write(html)
    except Exception as e:
        print(url, "ERR", e)


get("https://gokujan.com/review/5aaabe1a5fd507c3", "review")
get("https://gokujan.com/events/69289369", "event")