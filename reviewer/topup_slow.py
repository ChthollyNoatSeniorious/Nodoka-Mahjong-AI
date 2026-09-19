#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Slow single-account top-up: one account, one login, serial submissions
with a long delay between each, stops after --max-submits successes or when
the balance runs low. Designed to avoid triggering bigcoach risk control
(no mass multi-account login storms, no concurrency).

Reads/writes the same _state.json format as topup.py (merged, never clobbers
other state files).

Usage:
    python reviewer/topup_slow.py [--accounts Coach/bigcoach_account.active.txt]
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib
import re
import sys
import time

import urllib.error
import urllib.request
import http.cookiejar

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
RUNS = OUT / "bigcoach_runs"
STATE = RUNS / "_state.json"
ORIGIN = "https://review.bigcoach.work"
API = ORIGIN + "/api/v2"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
ID_RE = re.compile(r"([0-9a-f]{16})")
PAIPU_RE = re.compile(r"paipu=([A-Za-z0-9_.-]+)")


def load_all_results() -> list[dict]:
    out = []
    for f in sorted(glob.glob(str(RUNS / "_state*.json"))):
        try:
            d = json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        out += d.get("results", [])
    return out


def load_accounts(path) -> list[tuple[str, str]]:
    accts = []
    for l in pathlib.Path(path).read_text(encoding="utf-8-sig").splitlines():
        l = l.strip()
        if not l:
            continue
        p = l.split("|")
        accts.append((p[0].strip(), p[1].strip() if len(p) > 1 else ""))
    return accts


def open_login(email: str, password: str):
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = json.dumps({"email": email, "password": password}).encode()
    r = urllib.request.Request(API + "/auth/login", data=body,
                               headers={"User-Agent": UA,
                                        "Content-Type": "application/json"})
    try:
        with op.open(r, timeout=90) as resp:
            return op, resp.status
    except urllib.error.HTTPError as e:
        return op, e.code


def get_balance(op) -> int | None:
    r = urllib.request.Request(API + "/membership/status",
                               headers={"User-Agent": UA})
    try:
        with op.open(r, timeout=60) as resp:
            d = json.loads(resp.read().decode("utf-8", "replace"))["data"]
        c = d.get("credits") or {}
        if isinstance(c, dict):
            return int(c.get("balance") or 0)
        return int(c or 0)
    except Exception:
        return None


def submit(op, paipu: str) -> tuple[int, str]:
    mp = {"paipuId": paipu, "analysisMode": "standard", "ui": "auto",
          "language": "zh", "model4p": "rigel_14"}
    boundary = "----tp" + time.strftime("%H%M%S") + "x"
    parts = []
    for k, v in mp.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                     f'name="{k}"\r\n\r\n{v}\r\n')
    parts.append(f"--{boundary}--\r\n")
    data = "".join(parts).encode("utf-8")
    r = urllib.request.Request(API + "/review", data=data, method="POST",
                               headers={"User-Agent": UA,
                                        "Content-Type":
                                        f"multipart/form-data; boundary={boundary}",
                                        "Referer": ORIGIN + "/analyze"})
    try:
        with op.open(r, timeout=180) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def persist(hist: list[dict]):
    st = {"done": sorted({f"{r.get('account')}|{r.get('paipu')}"
                          for r in hist if r.get('paipu')}),
          "results": hist}
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1),
                     encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", type=str,
                    default=str(HERE.parent / "Coach" /
                                "bigcoach_account.active.txt"))
    ap.add_argument("--delay", type=int, default=20,
                    help="seconds between submissions")
    ap.add_argument("--max-submits", type=int, default=15,
                    help="stop after this many successful submissions")
    ap.add_argument("--retries", type=int, default=2,
                    help="retries per paipu on 503")
    ap.add_argument("--retry-wait", type=int, default=60)
    ap.add_argument("--min-balance", type=int, default=10)
    args = ap.parse_args()

    paipus = []
    for line in (OUT / "player72520_paipus.txt").read_text(encoding="utf-8").splitlines():
        m = PAIPU_RE.search(line)
        if m:
            paipus.append(m.group(1))
    all_paipus = set(paipus)

    accounts = load_accounts(args.accounts)
    if not accounts:
        print("no active accounts", flush=True)
        return 1
    print(f"paipus: {len(all_paipus)}, active accounts: {len(accounts)}",
          flush=True)

    hist = load_all_results()
    covered = set()
    for r in hist:
        if r.get("taskId") and r.get("paipu"):
            covered.add(r["paipu"])
    print(f"covered by recorded taskIds: {len(covered)}", flush=True)
    missing = sorted(all_paipus - covered, key=lambda x: paipus.index(x))
    print(f"missing: {len(missing)}", flush=True)
    if not missing:
        print("nothing to do", flush=True)
        return 0

    email, password = accounts[0]
    print(f"using account: {email}", flush=True)
    op, code = open_login(email, password)
    for _lg in range(4):
        if code == 429:
            print("login 429, sleeping 60s", flush=True)
            time.sleep(60)
            op, code = open_login(email, password)
        else:
            break
    if code != 200:
        print(f"login failed: HTTP {code}", flush=True)
        return 2
    print("login ok", flush=True)
    bal = get_balance(op)
    print(f"balance: {bal}", flush=True)
    if bal is None or bal < args.min_balance:
        print("balance unreadable or too low, abort", flush=True)
        return 3

    n_ok = 0
    n_fail = 0
    n_invalid = 0
    relogins = 0
    for paipu in missing:
        if n_ok >= args.max_submits:
            print(f"reached max-submits={args.max_submits}, stopping", flush=True)
            break
        cur_bal = get_balance(op)
        if cur_bal is not None and cur_bal < args.min_balance:
            print(f"balance low ({cur_bal}), stopping", flush=True)
            break

        st, txt = 0, ""
        ok = False
        for attempt in range(1, args.retries + 2):
            try:
                st, txt = submit(op, paipu)
            except Exception as e:
                print(f"  {paipu[:26]}... submit exception: {e}", flush=True)
                st = 0
                time.sleep(args.retry_wait)
                continue
            if st == 200 and ID_RE.search(txt):
                tid = ID_RE.search(txt).group(1)
                hist.append({"account": email, "paipu": paipu,
                             "taskId": tid, "status": "submitted",
                             "note": "topup-slow"})
                covered.add(paipu)
                n_ok += 1
                print(f"  OK {n_ok}/{args.max_submits} "
                      f"{paipu[:26]}... -> {tid}", flush=True)
                persist(hist)
                ok = True
                break
            if st == 429:
                # daily per-account limit (5 games/day): 429 means the day's
                # quota is exhausted; retrying is futile and only adds risk.
                print(f"  {paipu[:26]}... 429 -> day quota used up, "
                      f"batch stopped", flush=True)
                persist(hist)
                return 7
            if st == 401:
                print(f"  {paipu[:26]}... session expired, relogin", flush=True)
                relogins += 1
                if relogins > 3:
                    print("too many relogins, abort", flush=True)
                    return 4
                op, code = open_login(email, password)
                if code != 200:
                    print(f"  relogin failed HTTP {code}", flush=True)
                    return 5
                continue
            if st == 503:
                print(f"  {paipu[:26]}... 503 attempt {attempt}, "
                      f"sleeping {args.retry_wait}s", flush=True)
                time.sleep(args.retry_wait)
                continue
            if st == 402 or "INSUFFICIENT" in txt:
                print(f"  {paipu[:26]}... 402 INSUFFICIENT, account dry, "
                      f"stopping", flush=True)
                return 6
            if st == 400 and "INVALID_PAIPU" in txt:
                hist.append({"account": email, "paipu": paipu,
                             "status": "submit HTTP 400"})
                n_invalid += 1
                print(f"  INVALID {paipu[:26]}...", flush=True)
                ok = True  # do not retry this paipu
                break
            # other hard errors
            hist.append({"account": email, "paipu": paipu,
                         "status": f"submit HTTP {st}"})
            n_fail += 1
            print(f"  FAIL {paipu[:26]}... {st} {txt[:80]}", flush=True)
            ok = True
            break
        if not ok:
            hist.append({"account": email, "paipu": paipu,
                         "status": "submit HTTP 503"})
            n_fail += 1
            print(f"  STORM {paipu[:26]}... (retries exhausted)", flush=True)
        if ok and n_ok < args.max_submits:
            print(f"  sleep {args.delay}s...", flush=True)
            time.sleep(args.delay)

    persist(hist)
    print(f"\nbatch done: ok={n_ok}, invalid={n_invalid}, fails={n_fail}, "
          f"covered={len(covered)}/{len(all_paipus)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())