"""Are the 1765 files really 1765 distinct games, or ~441 games x 4 seats?

The tw distribution (400/474/442/449) is suspiciously even across the four
seats.  If the exporter saved each game once per seat, then:
  * the number of DISTINCT games is ~1765/4
  * every game is present 4 times, so harvesting pi for all of them would
    triple-count

This matters for (a) how much unique training data we really have, and
(b) how many bigcoach reviews we actually need to run.
"""
import collections
import glob
import pathlib
import re

files = sorted(glob.glob("date/*.json.gz"))
pat = re.compile(r"^(\d{10}gm-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{8})&tw=(\d)\.json\.gz$")

by_log = collections.defaultdict(list)
for f in files:
    m = pat.match(pathlib.Path(f).name)
    if m:
        by_log[m.group(1)].append(m.group(2))

print(f"files          : {len(files)}")
print(f"distinct log_id: {len(by_log)}")
print()

sizes = collections.Counter(len(v) for v in by_log.values())
print("how many tw variants per log_id:")
for k in sorted(sizes):
    print(f"  {k} variant(s) : {sizes[k]} log_ids")
print()

tw_sets = collections.Counter(tuple(sorted(v)) for v in by_log.values())
print("tw sets seen:")
for k, v in tw_sets.most_common(10):
    print(f"  {k} : {v}")
print()

if len(by_log) < len(files) * 0.9:
    print(f"=> DUPLICATED: {len(files)} files cover only {len(by_log)} distinct games")
    print(f"   ({len(files)/len(by_log):.2f} files per game)")
else:
    print("=> all files are distinct games")
