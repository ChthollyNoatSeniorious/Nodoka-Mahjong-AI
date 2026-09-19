"""Inspect the raw tenhou mjlog2json response so we can convert it correctly."""
import json
import sys
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

LOG_ID = "2025071422gm-00a9-0000-a1375e41"
url = f"https://tenhou.net/5/mjlog2json.cgi?{LOG_ID}"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=60) as r:
    raw = r.read().decode("utf-8")

print(f"raw length: {len(raw)}")
print("first 500 chars:")
print(raw[:500])
print()

obj = json.loads(raw)
print(f"top-level type: {type(obj).__name__}")
if isinstance(obj, dict):
    print(f"keys: {list(obj.keys())}")
    for k, v in obj.items():
        if isinstance(v, list):
            print(f"  {k}: list of {len(v)}")
            if v:
                print(f"     first item type: {type(v[0]).__name__}")
                print(f"     first item: {json.dumps(v[0], ensure_ascii=False)[:200]}")
        else:
            print(f"  {k}: {type(v).__name__} = {str(v)[:120]}")
elif isinstance(obj, list):
    print(f"len: {len(obj)}")
    for i, item in enumerate(obj[:12]):
        print(f"  [{i}] {type(item).__name__}: {json.dumps(item, ensure_ascii=False)[:160]}")
