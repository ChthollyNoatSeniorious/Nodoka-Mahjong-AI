#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Harvest Akino Hana ("長明 RIGEL 1.4") pi-value reviews from bigcoach.

WHY
---
Our own training logs only record *which* tile Akino Hana discarded.  The
bigcoach review service additionally reports the full action distribution
``pi_tau(a|s)`` for every decision.  That distribution is what we need to
distil the *policy* rather than just imitate the argmax.

HOW (reverse engineered from the browser network log)
-----------------------------------------------------
    POST /api/v2/tasks                     -> {task_id, ...}      submit a paipu
    GET  /api/v2/tasks/{id}                -> progress            (poll / ws)
    GET  /api/v2/tasks/{id}                -> result
    GET  /api/v2/tasks/{id}/classic?token=BASE64(id)   -> the classic HTML report
                                                            (same format as
                                                             `Test set/*.htm`)
The ``token`` is simply ``base64(task_id)`` -- verified against test03.

The classic report is what we want: it contains, for every one of the ~216
decisions in a game, the hand, the player's action, Akino Hana's top-1 action
and the full normalised pi table (it sums to exactly 100 over all legal
actions, verified on test03: 213/216 candidate counts match the true mask).

USAGE
-----
    # one game, by tenhou URL
    python reviewer\\bigcoach_harvest.py -u "https://tenhou.net/3/?log=...&tw=2"

    # a list of URLs, one per line
    python reviewer\\bigcoach_harvest.py --url-file paipus.txt

    # where to put the reports (default: reviewer/out/bigcoach)
    python reviewer\\bigcoach_harvest.py --url-file paipus.txt --out-dir myreports

AUTH
----
The service is behind a login.  Put your session cookie in the environment
variable ``BIGCOACH_COOKIE`` (copy it from DevTools -> Network -> any request ->
Request Headers -> cookie) or pass ``--cookie``.  Nothing is written to disk.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_OUT = HERE / "out" / "bigcoach"

BASE = "https://review.bigcoach.work"
API = BASE + "/api/v2"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")


# --------------------------------------------------------------------------- #
# tiny HTTP helper
# --------------------------------------------------------------------------- #
def request(method: str, url: str, cookie: str | None = None,
            body: dict | None = None, accept: str = "application/json",
            timeout: int = 60) -> tuple[int, bytes, dict]:
    headers = {
        "User-Agent": UA,
        "Accept": accept,
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }
    if cookie:
        headers["Cookie"] = cookie
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})


def classic_token(task_id: str) -> str:
    """The classic-report token is just the base64 of the task id."""
    return base64.b64encode(task_id.encode()).decode()


# --------------------------------------------------------------------------- #
# workflow
# --------------------------------------------------------------------------- #
def submit(cookie: str, paipu: str, model: str | None) -> dict:
    """Create a review task for a paipu URL."""
    payload = {"paipu": paipu, "url": paipu}
    if model:
        payload["model"] = model
    status, raw, _ = request("POST", f"{API}/tasks", cookie, payload)
    if status not in (200, 201, 202):
        raise RuntimeError(f"submit failed: HTTP {status}: {raw[:400]!r}")
    try:
        return json.loads(raw)
    except Exception:
        raise RuntimeError(f"submit returned non-JSON: {raw[:400]!r}")


def poll(cookie: str, task_id: str, timeout: float = 900.0,
         interval: float = 3.0) -> dict:
    """Wait until the task is done; return the final payload."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status, raw, _ = request("GET", f"{API}/tasks/{task_id}", cookie)
        if status == 200:
            try:
                last = json.loads(raw)
            except Exception:
                last = {"raw": raw[:400].decode("utf-8", "replace")}
            state = str(last.get("status", "")).lower()
            if state in ("done", "finished", "success", "completed", "ok"):
                return last
            if state in ("failed", "error"):
                raise RuntimeError(f"task failed: {last}")
        time.sleep(interval)
    raise TimeoutError(f"task {task_id} not finished in {timeout}s (last={last})")


def fetch_classic(cookie: str, task_id: str) -> str:
    """Download the classic HTML report (the format `Test set/*.htm` uses)."""
    tok = classic_token(task_id)
    url = f"{API}/tasks/{task_id}/classic?token={urllib.parse.quote(tok)}"
    status, raw, _ = request("GET", url, cookie, accept="text/html,*/*")
    if status != 200:
        raise RuntimeError(f"classic report failed: HTTP {status}: {raw[:300]!r}")
    return raw.decode("utf-8", "replace")


# --------------------------------------------------------------------------- #
def harvest_one(cookie: str, paipu: str, out_dir: Path, model: str | None,
                force: bool = False) -> Path:
    """Submit one paipu and save its classic report. Returns the saved path."""
    # task id is unknown before submitting, so always submit; but we can reuse a
    # report if we can derive a stable name from the paipu.
    m = re.search(r"log=([0-9a-z\-]+)", paipu)
    log_id = m.group(1) if m else re.sub(r"\W+", "_", paipu)[-40:]
    tw = ""
    m2 = re.search(r"tw=(\d)", paipu)
    if m2:
        tw = f"&tw={m2.group(1)}"
    dest = out_dir / f"{log_id}{tw}.htm"
    if dest.is_file() and not force:
        print(f"  [skip] already have {dest.name}")
        return dest

    print(f"  submitting ...")
    info = submit(cookie, paipu, model)
    task_id = (info.get("id") or info.get("task_id") or info.get("taskId")
               or (info.get("data") or {}).get("id"))
    if not task_id:
        raise RuntimeError(f"could not find task id in submit response: {info}")
    print(f"  task id {task_id}, waiting ...")

    poll(cookie, str(task_id))
    html = fetch_classic(cookie, str(task_id))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")
    print(f"  saved -> {dest}  ({len(html):,} bytes)")
    return dest


def urls_from_dataset(date_dir: pathlib.Path, seats: str = "0",
                      limit: int | None = None) -> list[str]:
    """Derive tenhou URLs from the training-set filenames.

    Each `date/*.json.gz` is named after its tenhou log id, so the training
    distribution can be harvested directly -- no need to source new games.

        <log_id>&tw=<n>.json.gz   ->   https://tenhou.net/3/?log=<log_id>&tw=<n>

    `seats` picks which seat(s) to review ("0", "0,2", or "all").  One bigcoach
    review covers one seat, and libriichi trains on all four, so "all" gives 4x
    coverage at 4x the review cost.
    """
    pat = re.compile(r"^(\d{10}gm-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{8})&tw=(\d)\.json\.gz$")
    wanted = None if seats == "all" else set(seats.split(","))
    urls = []
    for f in sorted(date_dir.glob("*.json.gz")):
        m = pat.match(f.name)
        if not m:
            continue
        log_id, tw = m.groups()
        if wanted is not None and tw not in wanted:
            continue
        urls.append(f"https://tenhou.net/3/?log={log_id}&tw={tw}")
        if limit and len(urls) >= limit:
            break
    return urls


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Harvest Akino Hana pi-value reviews from bigcoach.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("-u", "--url", help="one tenhou/majsoul paipu URL")
    src.add_argument("--url-file", type=Path, help="file with one URL per line")
    src.add_argument("--from-dataset", action="store_true",
                     help="derive URLs from mortal/date/*.json.gz filenames")
    ap.add_argument("--date-dir", type=Path, default=ROOT / "mortal" / "date")
    ap.add_argument("--seats", default="0",
                    help='which seats to review: "0", "0,2" or "all" (default: 0)')
    ap.add_argument("--limit", type=int, help="stop after N games (for a trial run)")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--cookie", default=os.environ.get("BIGCOACH_COOKIE"),
                    help="session cookie (or set BIGCOACH_COOKIE)")
    ap.add_argument("-m", "--model", default="rigel-1.4",
                    help="model alias to review with (default: %(default)s)")
    ap.add_argument("--delay", type=float, default=2.0,
                    help="seconds between games (be polite)")
    ap.add_argument("--force", action="store_true", help="re-download existing")
    ap.add_argument("--dry-run", action="store_true",
                    help="only probe the API shapes, submit nothing")
    args = ap.parse_args()

    if not args.cookie:
        print("ERROR: no cookie. Set BIGCOACH_COOKIE or pass --cookie.\n"
              "  DevTools -> Network -> any request -> Request Headers -> cookie",
              file=sys.stderr)
        return 2

    urls = [args.url] if args.url else [
        ln.strip() for ln in args.url_file.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")] if args.url_file else \
        urls_from_dataset(args.date_dir, args.seats, args.limit)
    print(f"{len(urls)} paipu(s) to harvest -> {args.out_dir}")

    if args.dry_run:
        print("dry run: probing /api/v2/tasks shape only")
        st, raw, _ = request("GET", f"{API}/tasks", args.cookie)
        print(f"  GET {API}/tasks -> {st}: {raw[:300]!r}")
        return 0

    ok = fail = 0
    for i, u in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {u}")
        try:
            harvest_one(args.cookie, u, args.out_dir, args.model, args.force)
            ok += 1
        except Exception as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            fail += 1
        if i < len(urls):
            time.sleep(args.delay)

    print(f"\ndone: {ok} ok, {fail} failed")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
