#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Top-up pass: submit every paipu from the 500 list that has no recorded
successful taskId, using accounts that still have credits (failures like
503/INSUFFICIENT cost nothing; done-keys are IGNORED here -- the coverage
map is taskId presence, not done-keys).

Designed for upstream 503 storms: per submission retry up to --retries
times with growing backoff; whole-run rounds repeat until the missing set
is empty or --rounds exhausted, sleeping --round-wait between rounds.

Usage:
    python reviewer/topup.py [--rounds 6] [--round-wait 600] [--retries 15]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
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


def load_accounts() -> list[str]:
    p = HERE.parent / "Coach" / "bigcoach_account.txt"
    return [l.split("|")[0].strip()
            for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def get_password() -> str:
    # avoid hardcoding credentials in the repo; set BIGCOACH_PASSWORD in env
    return os.environ.get("BIGCOACH_PASSWORD", "")


def open_login(email: str, password: str):
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = json.dumps({"email": email, "password": password}).encode()
    r = urllib.request.Request(API + "/auth/login", data=body,
                               headers={"User-Agent": UA,
                                        "Content-Type": "application/json"})
    try:
        with op.open(r, timeout=60) as resp:
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
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--round-wait", type=int, default=600)
    ap.add_argument("--retries", type=int, default=4)
    ap.add_argument("--max-invalid-accts", type=int, default=4)
    ap.add_argument("--accounts", type=str,
                    default=str(HERE.parent / "Coach" / "bigcoach_account.txt"))
    args = ap.parse_args()

    paipus = []
    for line in (OUT / "player72520_paipus.txt").read_text(encoding="utf-8").splitlines():
        m = PAIPU_RE.search(line)
        if m:
            paipus.append(m.group(1))
    all_paipus = set(paipus)

    accounts = load_accounts()
    print(f"paipus: {len(all_paipus)}, accounts: {len(accounts)}")

    hist = load_all_results()
    covered = set()
    for r in hist:
        if r.get("taskId") and r.get("paipu"):
            covered.add(r["paipu"])
    print(f"covered by recorded taskIds: {len(covered)}")

    missing = all_paipus - covered
    print(f"missing: {len(missing)} -> first pass backlog")
    missing = sorted(missing, key=lambda x: paipus.index(x))

    # per-account spent tracking (this script re-checks balance after each use)
    spent: dict[str, int] = {}
    failures: dict[str, str] = {}
    n_invalid: dict[str, int] = {}
    max_invalid_accts = args.max_invalid_accts

    round_no = 0
    while missing and round_no < args.rounds:
        round_no += 1
        newly = []
        storm_hits = 0
        for paipu in missing:
            if storm_hits >= 8:
                print("  (storm detected, ending round early)", flush=True)
                break
            done = False
            used_accts = []
            for email in accounts:
                # quick check: skip accounts we know are dry
                if spent.get(email, 0) >= 15:
                    used_accts.append(email)
                    continue
                op, code = open_login(email, get_password())
                for _lg in range(3):
                    if code == 429:
                        time.sleep(30)
                        op, code = open_login(email, get_password())
                    else:
                        break
                if code != 200:
                    used_accts.append(email)
                    continue
                bal = get_balance(op)
                if bal is None or bal < 10:
                    spent[email] = 15
                    used_accts.append(email)
                    continue
                ok = False
                st = 0
                txt = ""
                for attempt in range(1, args.retries + 1):
                    st, txt = submit(op, paipu)
                    if st == 200 and ID_RE.search(txt):
                        tid = ID_RE.search(txt).group(1)
                        hist.append({"account": email, "paipu": paipu,
                                     "taskId": tid, "status": "submitted",
                                     "note": "topup"})
                        spent[email] = spent.get(email, 0) + 1
                        covered.add(paipu)
                        newly.append((email, paipu, tid))
                        print(f"  OK {paipu[:26]}... -> {tid} ({email})",
                              flush=True)
                        ok = True
                        done = True
                        if len(newly) % 20 == 0:
                            persist(hist)
                        break
                    if st == 429:
                        time.sleep(30.0)
                        continue
                    if st == 503:
                        time.sleep(min(30 * attempt, 60))
                        storm_hits += 1
                        continue
                    # non-transient: exit inner retry loop
                    break
                if ok:
                    break
                if done:
                    break
                if st == 402 or "INSUFFICIENT" in txt:
                    spent[email] = 15  # dry
                    continue
                if st == 400 and "INVALID_PAIPU" in txt:
                    # often transient: try a few accounts, then defer to a
                    # later round (never permanently exclude)
                    n_invalid[paipu] = n_invalid.get(paipu, 0) + 1
                    if n_invalid[paipu] >= max_invalid_accts:
                        failures[paipu] = "INVALID_PAIPU x" + \
                            str(n_invalid[paipu])
                        print(f"  INVALID {paipu[:26]}... "
                              f"(x{n_invalid[paipu]})", flush=True)
                        done = True
                        break
                    time.sleep(4)
                    continue
                failures[paipu] = f"{st}:{txt[:100]}"
                print(f"  FAIL {paipu[:26]}... [{email}] {st} "
                      f"{txt[:80]}", flush=True)
                done = True  # hard error: give up
                time.sleep(5)
                break
            if not done:
                print(f"  DEFER {paipu[:26]}... (no account succeeded)", flush=True)
        missing = sorted(all_paipus - covered, key=lambda x: paipus.index(x))
        print(f"round {round_no}: ok={len(newly)}, missing now "
              f"{len(missing)}", flush=True)
        if missing and round_no < args.rounds:
            print(f"sleeping {args.round_wait}s before round {round_no + 1}...",
                  flush=True)
            time.sleep(args.round_wait)

    # persist back into main state
    st = {"done": sorted({f"{r.get('account')}|{r.get('paipu')}"
                          for r in hist if r.get('paipu')}),
          "results": hist}
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    print(f"\nfinal: covered={len(covered)}/{len(all_paipus)}")
    if failures:
        print("hard failures (not retried):")
        for k, v in list(failures.items())[:20]:
            print(f"  {k[:30]}... {v[:80]}")
        print(f"  ... {len(failures)} total")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())