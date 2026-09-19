"""Decode the token from the classic report URL.

User saw:  classic?token=NzRjMjAxOWQ3MTE4YzI4X...
test03 filename contains: 74c2019d71

If base64("74c2019d71") == "NzRjMjAxOWQ3MTE4YzI4..." then the token is just the
task id encoded, which means we can construct the classic-report URL ourselves
from the task id -- no browser needed.
"""
import base64

tok = "NzRjMjAxOWQ3MTE4YzI4"
# pad to a multiple of 4 for decoding
padded = tok + "=" * (-len(tok) % 4)
try:
    print("decoded:", base64.b64decode(padded))
except Exception as e:
    print("decode failed:", e)

print()
print("expected task id fragment: 74c2019d71")
print("base64('74c2019d71') =", base64.b64encode(b"74c2019d71").decode())
