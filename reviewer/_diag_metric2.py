"""Does the inflation affect Akino Hana's baseline the same way?

If the human forced-pass decisions are credited to Akino Hana too, then the
headline deviation is still an apples-to-apples comparison, and the real
discard-only number is the honest one for BOTH sides.
"""
import re
import sys
import collections
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("c", r"reviewer\compare_test03.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ak = [e for k in m.parse_akino(next(m.TESTSET.glob("test03_*.htm"))) for e in k]

print("=== Akino Hana on test03, decomposed ===")
print("total decisions        :", len(ak))
none_ent = [e for e in ak if e["player_key"] == "none"]
print("human forced-pass      :", len(none_ent))
print("  Akino Hana 'agrees'  :", sum(1 for e in none_ent if e["rank"] == 1))
print()
dahai = [e for e in ak if e["player_key"].startswith("dahai:")]
d_eq = sum(1 for e in dahai if e["rank"] == 1)
print("real discard decisions :", len(dahai))
print("  Akino Hana agrees    : %d/%d = %.4f" % (d_eq, len(dahai), d_eq / len(dahai)))
print()
tot = sum(1 for e in ak if e["rank"] == 1)
print("headline               : %d/%d = %.4f" % (tot, len(ak), tot / len(ak)))

# now our adopted model on the same real-discard subset
ours, _ = m.load_ours(m.JSON_DIR / "test03_finetune_step321275.json")
o = [x for k in ours for x in k]
o_dahai = [x for x in o if x["actual_key"].startswith("dahai:")]
o_eq = sum(1 for x in o_dahai if x["is_equal"])
print()
print("=== adopted model, same subset ===")
print("  our model agrees     : %d/%d = %.4f" % (o_eq, len(o_dahai), o_eq / len(o_dahai)))
print()
print("=== deviation on REAL DISCARDS only ===")
print("  headline deviation   : %+.2f pts" % (
    100.0 * sum(1 for x in o if x["is_equal"]) / len(o) - 100.0 * tot / len(ak)))
print("  discard-only deviation: %+.2f pts" % (
    100.0 * o_eq / len(o_dahai) - 100.0 * d_eq / len(dahai)))
