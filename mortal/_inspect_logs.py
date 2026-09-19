"""Inspect the training logs: do they contain Akino Hana's full action distribution?"""
import collections
import glob
import gzip
import json

f = sorted(glob.glob("date/*.json.gz"))[0]
print("file:", f)
with gzip.open(f, "rt", encoding="utf-8") as fh:
    lines = [json.loads(x) for x in fh if x.strip()]

print("events:", len(lines))
print()
print("=== event type distribution ===")
print(dict(collections.Counter(e.get("type") for e in lines)))
print()
print("=== first 5 events, full JSON ===")
for e in lines[:5]:
    print(json.dumps(e, ensure_ascii=False))
print()

# look for any field that could hold a probability / distribution / q values
print("=== all keys seen anywhere ===")
keys = collections.Counter()
for e in lines:
    for k in e:
        keys[k] += 1
print(dict(keys))
print()

# check the meta event specifically
for e in lines:
    if e.get("type") == "meta":
        print("=== meta event ===")
        print(json.dumps(e, ensure_ascii=False, indent=1)[:2000])
        break
