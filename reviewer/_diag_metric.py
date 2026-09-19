"""Dig into what the test-set agreement metric actually counts."""
import collections
import json
import pathlib

P = pathlib.Path(r"reviewer\out\testset")

print("=== test03 checkpoints ===")
for f in sorted(P.glob("test03_*.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    r = d["review"]
    print("%-46s matches=%4s reviewed=%4s tag=%s" % (
        f.stem, r["total_matches"], r["total_reviewed"], r.get("model_tag")))

print()
print("=== what is inside those 216 decisions (321k model) ===")
d = json.loads((P / "test03_finetune_step321275.json").read_text(encoding="utf-8"))
ent = [e for k in d["review"]["kyokus"] for e in k["entries"]]

print("actual types :", dict(collections.Counter(e["actual"]["type"] for e in ent)))
print("expect types :", dict(collections.Counter(e["expected"]["type"] for e in ent)))
print()

none_ent = [e for e in ent if e["actual"]["type"] == "none"]
print("decisions where the human had NO action (forced pass):", len(none_ent))
print("  counted as agreement anyway                      :",
      sum(1 for e in none_ent if e["is_equal"]))
print()

dahai = [e for e in ent if e["actual"]["type"] == "dahai"]
d_eq = sum(1 for e in dahai if e["is_equal"])
print("real discard decisions :", len(dahai))
print("  model agreed         :", d_eq, "=> %.4f" % (d_eq / len(dahai)))
print()
tot_eq = sum(1 for e in ent if e["is_equal"])
print("headline metric        : %d/%d = %.4f" % (tot_eq, len(ent), tot_eq / len(ent)))
print("of which forced-pass   : %d (%.1f%% of all credited agreements)"
      % (len(none_ent), 100.0 * len(none_ent) / tot_eq))
