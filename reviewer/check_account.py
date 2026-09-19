#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot account health check: login + balance for the FIRST active
account. Use sparingly."""
import sys, pathlib
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import topup_slow as t

accts = t.load_accounts(HERE.parent / "Coach" / "bigcoach_account.active.txt")
if not accts:
    print("no active accounts")
    sys.exit(1)
email, password = accts[0]
print("account:", email, flush=True)
op, code = t.open_login(email, password)
print("login:", code, flush=True)
if code == 200:
    print("balance:", t.get_balance(op), flush=True)