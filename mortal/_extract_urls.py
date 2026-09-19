"""Can we generate the tenhou URLs for the 1765 self-play logs automatically?

The dataset filenames look like:
    2025031220gm-0009-0000-6233fed3&tw=0.json.gz
which is exactly a tenhou log id plus the POV seat.  If so, we already have
every URL we need to harvest pi values for the training data -- no need to
source new games.

This script extracts them and checks the tw distribution.
"""
import collections
import glob
import pathlib
import re

files = sorted(glob.glob("date/*.json.gz"))
print(f"files: {len(files)}")
print()

pat = re.compile(r"^(\d{10}gm-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{8})&tw=(\d)\.json\.gz$")
ok = collections.Counter()
bad = []
tw_counts = collections.Counter()

for f in files:
    name = pathlib.Path(f).name
    m = pat.match(name)
    if m:
        ok["matched"] += 1
        tw_counts[m.group(2)] += 1
    else:
        ok["unmatched"] += 1
        if len(bad) < 10:
            bad.append(name)

print("filename parse:", dict(ok))
print("tw distribution:", dict(tw_counts))
if bad:
    print()
    print("unmatched examples:")
    for b in bad:
        print("  ", b)
print()

# sample URLs
print("=== sample URLs we could submit to bigcoach ===")
n = 0
for f in files[:3]:
    m = pat.match(pathlib.Path(f).name)
    if m:
        log_id, tw = m.groups()
        print(f"  https://tenhou.net/3/?log={log_id}&tw={tw}")
        n += 1
print()
print(f"=> {ok['matched']} URLs derivable directly from the training set filenames.")
print(f"   With tw=0..3 (all four seats are Akino Hana in self-play) that is")
print(f"   {ok['matched']*4} reviews, i.e. ~4x the decisions from the same games.")
