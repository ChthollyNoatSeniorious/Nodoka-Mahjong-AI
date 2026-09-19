#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sync the account's review runs into the free-harvest pool.

Two input paths:

  1. ACCOUNT HISTORY (default) -- the account keeps a full history:

        GET /api/v2/membership/history?limit=N&offset=0
          -> items[]: { taskId, platform, nplayer, modelName, paipuId, ... }

     Any review the user runs on this account -- manual hall-of-fame submits
     or paid /review runs -- is picked up automatically.

  2. URL LIST FILE (--urls-file) -- a plain text file with one review URL per
     line, e.g. what the user pastes into a txt after manual runs:

        https://review.bigcoach.work/review/0bf1355b37c7396a
        https://tenhou.net/3/?log=2020100913gm-0041-0000-388c8bcb

     taskIds are extracted and fetched directly.

Either way the result payload is saved as reviewer/out/hof_free/<gid>.json and
the index is updated.  Read-only against the quota (downloads existing results).

    python reviewer\\sync_manual_runs.py [--limit 200] [--urls-file runs.txt]
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

API = "https://review.bigcoach.work/api/v2"
ORIGIN = "https://review.bigcoach.work"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
COOKIE = os.environ.get("BIGCOACH_COOKIE", "")


def call(url):
    if url.startswith("/api/"):
        url = ORIGIN + url
    elif url.startswith("/"):
        url = API + url
    r = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json", "Cookie": COOKIE,
        "Referer": "https://gokujan.com/"})
    try:
        with urllib.request.urlopen(r, timeout=90) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


def gid_from_url(pid: str) -> str:
    """log/paipu id from a tenhou/majsoul URL; strips &tw=<seat>."""

    pid = (pid or "").strip()
    if "log=" in pid:
        g = pid.split("log=")[-1]
    elif "paipu=" in pid:
        g = pid.split("paipu=")[-1]
    else:
        g = pid.rsplit("/", 1)[-1]
    g = g.split("&")[0].split("?")[0].strip()
    import re
    g = re.sub(r"&tw=\d+$", "", g)
    return g


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200,
                    help="max history entries to scan")
    ap.add_argument("--urls-file", default=None,
                    help="txt file with one review/paipu URL per line")
    ap.add_argument("--out-dir", default="reviewer/out/hof_free")
    args = ap.parse_args()

    out = pathlib.Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    idx_p = out / "_index.json"
    index = json.loads(idx_p.read_text(encoding="utf-8")) if idx_p.is_file() else {}

    # ---- 0. build the task list ---------------------------------------- #
    manual = []
    if args.urls_file:
        p = pathlib.Path(args.urls_file)
        if not p.is_file():
            print(f"urls file not found: {p}")
            return 1
        seen = set()
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            if "/review/" in line:
                task = line.split("/review/")[-1].split("?")[0].strip()
            elif "log=" in line:
                task = None
            else:
                task = line
            if task in seen:
                continue
            seen.add(task)
            manual.append({"taskId": task, "paipuId": line})
        print(f"urls file: {len(manual)} unique entries")
        items = manual
    else:
        items = []

    # ---- 1. list the account history (paginated, limit <= 100) ---------- #
    #      (only when no urls file was given)
    if not args.urls_file:
        items = []
        total = 0
        offset = 0
        page_size = min(100, args.limit)
        while offset < args.limit:
            st, txt = call(f"/membership/history?limit={page_size}&offset={offset}")
            if st != 200:
                print(f"history HTTP {st}: {txt[:200]}")
                return 1
            d = json.loads(txt).get("data") or {}
            chunk = d.get("items") or d.get("list") or []
            items.extend(chunk)
            total = d.get("total") or (offset + len(chunk))
            if len(chunk) < page_size:
                break
            offset += len(chunk)
        print(f"history: {len(items)} fetched / {total} total on account")

    # ---- 2. pick new 4p runs ------------------------------------------- #
    new = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("modelName") not in ("RIGEL 1.4", None):
            continue
        if it.get("nplayer") and it["nplayer"] != 4:
            continue
        pid = (it.get("paipuId") or "").strip()
        gid = None
        if args.urls_file:
            # taskId URLs: fetch history-like info later from the task itself
            task = it.get("taskId")
            if task and not str(task).startswith("http"):
                gid = None  # gid resolved after we fetch /result (has paipuId)
                new.append((f"task:{task}", it))
                continue
        if "log=" in pid:
            gid = pid.split("log=")[-1]
        elif "paipu=" in pid:
            gid = pid.split("paipu=")[-1]      # mahjong soul uuid
        else:
            gid = pid.rsplit("/", 1)[-1]
        gid = gid.split("&")[0].split("?")[0].strip()
        if not gid or gid in index:
            continue
        new.append((gid, it))
    print(f"new runs to sync: {len(new)}")

    # ---- 3. fetch each payload ------------------------------------------ #
    got = 0
    for gid, it in new:
        task = it.get("taskId")
        if gid.startswith("task:"):
            # resolve the actual paipu id from the result payload; paid
            # reviews have paipuInfo=null, so fall back to the taskId as key
            st, txt = call(f"/tasks/{task}/result")
            if st != 200:
                print(f"   {task}: result HTTP {st}")
                continue
            rj0 = json.loads(txt).get("data") or {}
            pid2 = rj0.get("paipuId") or ""
            gid = gid_from_url(pid2) if pid2 else ""
            if not gid or gid in index:
                gid = task  # fall back to taskId as storage key
            if gid in index:
                print(f"   task {task}: already indexed ({gid})")
                continue
            it = {"taskId": task, "paipuId": pid2, "playerId": None,
                  "analysisMode": rj0.get("analysisMode")}
        st, txt = call(f"/tasks/{task}/result")
        if st != 200:
            print(f"   {gid}: result HTTP {st}")
            continue
        rj = json.loads(txt).get("data") or {}
        ju = rj.get("jsonUrl")
        if not ju:
            print(f"   {gid}: no payload yet ({rj.get('modelName')!r})")
            continue
        s2, body = call(ju)
        if s2 != 200:
            print(f"   {gid}: data HTTP {s2}")
            continue
        rev = json.loads(body)
        rv = rev.get("review", {})
        kyo = rv.get("kyokus") or []
        ents = sum(len(k.get("entries") or []) for k in kyo)
        (out / f"{gid}.json").write_text(body, encoding="utf-8")
        index[gid] = {
            "taskId": task,
            "engine": rj.get("modelName") or it.get("modelName"),
            "player": None,
            "url": it.get("paipuId"),
            "playerId": it.get("playerId"),
            "paipuId": it.get("paipuId"),
            "mode": it.get("analysisMode"),
        }
        got += 1
        print(f"   + saved {gid}.json ({ents} entries, "
              f"{rj.get('modelName')})")
        idx_p.write_text(json.dumps(index, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        time.sleep(1)

    print(f"\nsynced {got} new reviews; pool now "
          f"{len([f for f in out.glob('*.json') if f.name != '_index.json'])} "
          f"games (index {len(index)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())