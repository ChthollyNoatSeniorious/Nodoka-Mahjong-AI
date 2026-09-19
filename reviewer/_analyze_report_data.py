"""Analyze one bigcoach htm report in full detail.

Purpose: determine EXACTLY what data each report contains, so we can decide
whether these reports can serve as distillation targets.

Key questions:
  Q1. Is the pi table a full distribution over ALL legal actions?
  Q2. Is tau recoverable? (is the pi a softmax of the Q values?)
  Q3. Are the Q values present, or only pi?
  Q4. How many decisions per report (i.e. how much data per manual run)?
"""
import collections
import importlib.util
import pathlib
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cmp", HERE / "compare_test03.py")
cmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp)

htm = next(cmp.TESTSET.glob("test03_*.htm"))
raw = htm.read_text(encoding="utf-8", errors="replace")
body = raw.split("</style>", 1)[1]
sections = re.split(r"<section[^>]*>", body)[1:]
ak = [e for s in sections for e in cmp.ENTRY_RE.findall(s)]
ak_flat = [e for k in cmp.parse_akino(htm) for e in k]

print("report:", htm.name)
print("decisions:", len(ak_flat))
print()

# --- Q1: how many candidates, and does the count match legal actions?
counts = collections.Counter(len(e["cands"]) for e in ak_flat)
print("=== Q1: candidates listed per decision ===")
for k in sorted(counts):
    print(f"  {k:>3} candidates : {counts[k]:>4} decisions")
print()

# --- Q2: sum of pi -- if it sums to 100 it is a normalised distribution
sums = []
for e in ak_flat:
    s = sum(c["pi"] for c in e["cands"])
    sums.append(s)
bad = [s for s in sums if abs(s - 100.0) > 1.5]
print("=== Q2: does pi sum to 100 (normalised over listed candidates)? ===")
print(f"  mean sum   : {sum(sums)/len(sums):.3f}")
print(f"  min / max  : {min(sums):.3f} / {max(sums):.3f}")
print(f"  off by >1.5: {len(bad)} decisions")
print()

# --- how many candidates did the report DROP (pi below a display threshold)?
print("=== how much probability mass is NOT listed? ===")
missing = [100.0 - s for s in sums]
print(f"  mean unlisted mass: {sum(missing)/len(missing):.4f}%")
print(f"  max  unlisted mass: {max(missing):.4f}%")
print()

# --- Q3: is there any Q value anywhere in the raw html?
print("=== Q3: does the raw html contain Q values? ===")
for pat in ["q_value", "q value", "Q(", "Q_", "qvalue", "logit", "pi_", "π"]:
    n = raw.count(pat)
    print(f"  {pat!r:12} : {n}")
print()
# show the table header to see what is actually displayed
m = re.search(r"<thead>.*?</thead>", raw, re.S)
if m:
    txt = re.sub(r"<[^>]+>", " ", m.group(0))
    print("  table header text:", " ".join(txt.split()))
print()

# --- Q4: how many decisions per kyoku / per report
print("=== Q4: data volume per report ===")
print(f"  total decisions in one game: {len(ak_flat)}")
print(f"  -> 100 games ~ {len(ak_flat)*100} training points")
print()

# --- the decisive question: are near-tie decisions common enough to matter?
print("=== distribution of Akino Hana's top-1 confidence ===")
bands = [(0, 30), (30, 40), (40, 50), (50, 60), (60, 80), (80, 101)]
for lo, hi in bands:
    n = sum(1 for e in ak_flat if e["cands"] and lo <= e["cands"][0]["pi"] < hi)
    lbl = f"{lo}-{hi if hi <= 100 else '100'}"
    bar = "#" * int(60.0 * n / len(ak_flat))
    print(f"  {lbl:>7} : {n:>4}  {bar}")
