import json
t = json.load(open("taxonomy.json"))
def walk(ns):
    for n in ns:
        yield n; yield from walk(n["children"])
out, seen = [], set()
def add(p, path):
    if p not in seen:
        seen.add(p); out.append((p, path))
for n in walk(t["tree"]):
    if n["children"] or "/" not in n["id"]:
        continue
    if n["facet"] == "identity":
        # "funny X stickers" + the first curated phrase (index 2 = first extra when present)
        picks = [n["search_phrases"][0]] + [p for p in n["search_phrases"][2:3] if " life sticker" not in p]
    else:
        picks = n["search_phrases"][:2]
    for p in picks:
        add(p, n["path"])
# a few high-level heads
for p in ["funny stickers", "funny bumper stickers", "funny decals", "gag gifts", "stocking stuffers for adults", "funny laptop stickers"]:
    add(p, "Root")
json.dump(out, open("evidence/phrases.json", "w"), indent=0)
print(len(out))
