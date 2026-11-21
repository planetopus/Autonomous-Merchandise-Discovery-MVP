#!/usr/bin/env python3
"""Deterministic keyword-category tagger for concept-engine sticker lines.

Given a line + niche_pair + pattern (+ optional darkness/device), returns:
  primary_category, secondary_categories (3-6), etsy_tags (10-13, each <=20 chars),
  seo_phrases (longer buyer phrases), seo_title (<=140, website/Etsy), ebay_title (<=80).

Pure function of (input, taxonomy.json[, identity atlas]) - no randomness, no network.

Usage:
  python categorize.py --line "..." --pair "nurses x true crime" --pattern true_identity_stack [--darkness 1 --device irony]
  python categorize.py --gold path/to/gold_lines.json --out gold_lines_categorized.json
  add --atlas <identity_atlas dir> to merge identities from the identity atlas.
"""
import argparse, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TAX = next((p for p in [os.path.join(HERE, "taxonomy.json"),
                                os.path.join(HERE, "..", "data", "categories", "taxonomy.json")]
                    if os.path.exists(p)), os.path.join(HERE, "taxonomy.json"))

# Pattern -> product placements that suit the joke shape (fallbacks when no term matches)
PATTERN_PRODUCTS = {
    "official_warning_sign": ["product/bumper-stickers-car-decals", "product/hard-hat-stickers"],
    "self_defeating_sign": ["product/bumper-stickers-car-decals", "product/laptop-stickers"],
    "true_identity_stack": ["product/bumper-stickers-car-decals", "product/water-bottle-stickers"],
    "club_roster": ["product/bumper-stickers-car-decals", "product/water-bottle-stickers"],
    "cheerful_dark_label": ["product/water-bottle-stickers", "product/laptop-stickers"],
}
DEFAULT_PRODUCTS = ["product/water-bottle-stickers", "product/laptop-stickers"]
HUMOR_TITLE = {"humor/dark-humor": "Dark Humor", "humor/sarcastic": "Sarcastic", "humor/ironic-absurd": "Funny",
               "humor/oddly-specific": "Oddly Specific", "humor/relatable-wholesome": "Relatable",
               "humor/adult-humor": "Adult Humor", "humor/meme-gen-z-slang": "Meme", "humor/fake-warning-signs": "Warning Sign",
               "humor/self-deprecating": "Self-Deprecating", "humor/fake-credentials-awards": "Funny Award"}
GENERIC_TAGS = ["funny sticker", "vinyl decal", "gag gift", "waterproof sticker", "funny gift", "sarcastic sticker"]


def walk(ns):
    for n in ns:
        yield n
        yield from walk(n["children"])


def term_re(t):
    t = t.strip()
    # tolerate simple plurals: "mechanic" also matches "mechanics"
    return re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?:s|es)?(?![a-z0-9])")


def _cap(w):
    if w.isupper() or any(c.isdigit() for c in w):
        return w
    i = next((k for k, c in enumerate(w) if c.isalpha()), None)
    return w if i is None else w[:i] + w[i].upper() + w[i + 1:]


def capwords(s):
    return " ".join(_cap(w) for w in s.split())


# ---------------- identity atlas merge (schema-tolerant) ----------------
def load_atlas(atlas_dir):
    """Returns [{id,label,group,self_terms}] from atlas JSON (preferred) or src/sg/*.txt pipe rows."""
    rows = []
    for p in sorted(glob.glob(os.path.join(atlas_dir, "*.json"))):
        try:
            d = json.load(open(p))
        except Exception:
            continue
        items = None
        if isinstance(d, dict) and isinstance(d.get("subgroups"), list):
            items = d["subgroups"]
        elif isinstance(d, dict):
            items = d.get("identities", d.get("groups", d))
        else:
            items = d
        if not isinstance(items, list):
            continue
        for it in items:
            if isinstance(it, dict) and it.get("id") and (it.get("label") or it.get("name")):
                st = it.get("self_terms") or it.get("aliases") or []
                if isinstance(st, str):
                    st = [x.strip() for x in st.split(",")]
                rows.append({"id": it["id"], "label": it.get("label") or it.get("name"),
                             "group": it.get("group") or it.get("parent_group") or it.get("category") or "Other",
                             "self_terms": st})
    if not rows:
        for p in sorted(glob.glob(os.path.join(atlas_dir, "src", "sg", "*.txt"))):
            for line in open(p):
                f = line.rstrip("\n").split("|")
                if len(f) >= 5 and f[0] and not f[0].startswith("#"):
                    rows.append({"id": f[0], "label": f[1], "group": f[2],
                                 "self_terms": [x.strip() for x in f[4].split(",") if x.strip()]})
    seen, out = set(), []
    for r in rows:
        if r["id"] not in seen:
            seen.add(r["id"]); out.append(r)
    return out


def merge_atlas(tax, atlas):
    ident_root = next(r for r in tax["tree"] if r["id"] == "identity")
    leaves = [n for n in walk([ident_root]) if not n["children"] and n["id"].count("/") >= 2]
    for a in atlas:
        lab = a["label"].lower()
        hit = None
        for n in leaves:
            names = {n["name"].lower(), n.get("singular", ""), n.get("plural", "")} | set(n["match_terms"])
            if lab in names or a["id"].replace("_", " ") in names:
                hit = n; break
        if hit:
            if a["id"] not in hit["atlas_ids"]:
                hit["atlas_ids"].append(a["id"])
            for t in a["self_terms"]:
                t = t.lower()
                if t and t not in hit["match_terms"] and len(t) > 2:
                    hit["match_terms"].append(t)
            continue
        gid = "identity/atlas-" + re.sub(r"[^a-z0-9]+", "-", a["group"].lower()).strip("-")
        g = next((c for c in ident_root["children"] if c["id"] == gid), None)
        if g is None:
            g = {"id": gid, "name": a["group"], "slug": gid.split("/")[1], "path": f"Who It's For > {a['group']}",
                 "facet": "identity", "short_tag": a["group"].lower()[:20], "search_phrases": [], "match_terms": [],
                 "children": []}
            ident_root["children"].append(g)
        sing = lab[:-1] if lab.endswith("s") and not lab.endswith("ss") else lab
        slug = re.sub(r"[^a-z0-9]+", "-", lab).strip("-")
        terms = sorted({lab, sing, a["id"].replace("_", " ")} | {t.lower() for t in a["self_terms"] if len(t) > 2})
        node = {"id": f"{gid}/{slug}", "name": a["label"], "slug": slug, "path": f"{g['path']} > {a['label']}",
                "facet": "identity", "short_tag": (sing + " sticker")[:20].strip(), "singular": sing, "plural": lab,
                "search_phrases": [f"funny {sing} stickers", f"gifts for {lab}", f"{sing} life sticker", f"funny {sing} decal"],
                "match_terms": terms, "atlas_ids": [a["id"]], "source": "identity_atlas", "children": []}
        g["children"].append(node)
        if len(g["search_phrases"]) < 6:
            g["search_phrases"].append(node["search_phrases"][0])
    return tax


def _identity_words(node):
    """Names a shopper would read as this identity, not generic product words."""

    words = set()
    for key in ("singular", "plural", "name"):
        for token in re.findall(r"[a-z0-9]+", (node.get(key) or "").lower()):
            if len(token) >= 3:
                words.add(token)
    for term in node.get("match_terms") or []:
        if " " in term or len(term) < 3:
            continue
        words.add(term.lower())
    return words


# ---------------- tagger ----------------
class Tagger:
    def __init__(self, tax):
        self.tax = tax
        self.nodes = {n["id"]: n for n in walk(tax["tree"])}
        self.leaves = [n for n in self.nodes.values() if not n["children"] and "/" in n["id"]]
        self.res = {n["id"]: [(t, term_re(t)) for t in n["match_terms"]] for n in self.leaves}
        self.identity_words = {
            n["id"]: _identity_words(n)
            for n in self.leaves
            if n.get("facet") == "identity"
        }

    def _topic_tag_ok(self, phrase, source, primary_id):
        """A secondary topic may not lend a tag that names a different identity."""

        if not phrase or source is None or source.get("facet") != "topic" or source.get("id") == primary_id:
            return True
        owned = self.identity_words.get(primary_id, set())
        lowered = phrase.lower()
        for ident, words in self.identity_words.items():
            if ident == primary_id:
                continue
            for word in words:
                if word in owned:
                    continue
                if term_re(word).search(lowered):
                    return False
        return True

    def _score(self, node, a, b, line):
        s, a_best = 0.0, 0.0
        for t, rx in self.res[node["id"]]:
            w = 1.0 + min(len(t), 12) / 24  # longer terms are more specific
            if rx.search(a): a_best = max(a_best, w)
            if rx.search(b): s += 2.5 * w
            if rx.search(line): s += 1 * w
        # niche A is who the joke is FOR, so a match there outranks any pile-up of line/topic hits
        return s + (10 * a_best if a_best else 0)

    def tag(self, line, niche_pair="", pattern="", darkness=0, device=""):
        L = line.lower()
        parts = [p.strip().lower() for p in re.split(r"\s+x\s+", niche_pair or "")]
        a = parts[0] if parts else ""
        b = " ".join(parts[1:]) if len(parts) > 1 else ""
        scored = {}
        for n in self.leaves:
            if n["facet"] in ("identity", "topic", "product"):
                s = self._score(n, a, b, L)
                if s > 0:
                    scored[n["id"]] = s
        by = lambda facet: sorted([k for k in scored if self.nodes[k]["facet"] == facet],
                                  key=lambda k: (-scored[k], k))
        ids, topics, prods = by("identity"), by("topic"), by("product")
        primary = ids[0] if ids else (topics[0] if topics else "humor/ironic-absurd")

        # humor styles (rule based)
        humor = []
        for n in self.nodes.values():
            if n["facet"] != "humor" or "/" not in n["id"]:
                continue
            r = n.get("rule", {})
            ok = False
            if "darkness_min" in r and darkness >= r["darkness_min"]: ok = True
            if "darkness_max" in r and darkness <= r["darkness_max"] and device != "sarcasm" and pattern in (
                    "true_identity_stack", "oddly_specific_vibe", "club_roster", "insider_deadpan_confession",
                    "seasonal_or_object_standoff", "situational_irony"): ok = True
            if pattern in r.get("patterns", []): ok = True
            if r.get("device") and r["device"] == device and pattern in r.get("patterns", []): ok = True
            if any(term_re(t).search(L) for t in n["match_terms"]): ok = True
            if ok:
                humor.append(n["id"])
        order = ["humor/dark-humor", "humor/sarcastic", "humor/fake-warning-signs", "humor/meme-gen-z-slang",
                 "humor/adult-humor", "humor/oddly-specific", "humor/self-deprecating", "humor/fake-credentials-awards",
                 "humor/ironic-absurd", "humor/relatable-wholesome"]
        humor = sorted(set(humor), key=order.index)
        if not humor:
            humor = ["humor/sarcastic" if device == "sarcasm" else "humor/ironic-absurd"]

        # occasions: explicit terms, or identity triggers from niche pair / primary
        occ = []
        trig_text = " ".join([a, b, L])
        for n in self.nodes.values():
            if n["facet"] != "occasion" or "/" not in n["id"]:
                continue
            if any(term_re(t).search(trig_text) for t in n["match_terms"]):
                occ.append((0, n["id"]))
            elif any(term_re(t).search(a) for t in n.get("identity_triggers", [])):
                occ.append((1, n["id"]))
        occ = [o for _, o in sorted(occ)]
        if not occ:
            occ = ["occasion/white-elephant-gag-gifts"]

        if not prods:
            prods = PATTERN_PRODUCTS.get(pattern, DEFAULT_PRODUCTS)

        # secondary: 1 more identity (if strong), top topic, top humor, top occasion, top product, then fill
        sec = []
        def push(x):
            if x and x != primary and x not in sec and len(sec) < 6:
                sec.append(x)
        if len(ids) > 1 and scored[ids[1]] >= 2: push(ids[1])
        if topics: push(topics[0])
        push(humor[0]); push(occ[0]); push(prods[0])
        for x in topics[1:2] + humor[1:2] + prods[1:2] + occ[1:2]:
            push(x)
        if len(sec) < 3:
            for x in DEFAULT_PRODUCTS + ["humor/ironic-absurd"]:
                push(x)

        P = self.nodes[primary]
        cats = [primary] + sec
        # ---- Etsy tags (<=20 chars, 10-13) ----
        tags = []
        def tadd(t, source=None):
            t = re.sub(r"\s+", " ", t.lower().replace("&", "and").replace("'", "")).strip()
            if source is not None and not self._topic_tag_ok(t, source, primary):
                return
            if t and len(t) <= 20 and t not in tags and len(tags) < 13:
                tags.append(t)
        sing = P.get("singular")
        if sing:
            tadd(f"funny {sing} sticker"); tadd(f"{sing} sticker"); tadd(f"{sing} gift"); tadd(f"{sing} decal")
            tadd(f"{sing} humor"); tadd(f"gift for {sing}")
        else:
            tadd(P["short_tag"])
        for c in cats[1:]:
            n = self.nodes[c]
            tadd(n["short_tag"], n)
            for ph in n["search_phrases"]:
                tadd(ph, n)
                if sum(1 for t in tags if t in n["search_phrases"]) >= 1:
                    break
        for g in GENERIC_TAGS:
            if len(tags) >= 12: break
            tadd(g)
        for c in cats:  # top up to >=10 from any short phrase
            node = self.nodes[c]
            for ph in node["search_phrases"]:
                if len(tags) >= 10: break
                tadd(ph, node)
        # ---- longer SEO phrases ----
        seo = []
        for c in cats:
            node = self.nodes[c]
            for ph in node["search_phrases"][:3 if c == primary else 2]:
                if not self._topic_tag_ok(ph, node, primary):
                    continue
                if ph not in seo:
                    seo.append(ph)
        seo = seo[:12]
        # ---- titles ----
        who = capwords(sing) if sing else P["name"]
        hname = HUMOR_TITLE.get(humor[0], "Funny")
        clean = re.sub(r"\s+", " ", line.strip().strip('"'))
        seo_title = f"Funny {who} Sticker – {clean} – {hname} Decal"
        if len(seo_title) > 140:
            seo_title = f"Funny {who} Sticker – {clean[:140 - len(who) - 40].rsplit(' ', 1)[0]}… – {hname} Decal"
        eline = capwords(clean.lower()) if clean.isupper() else clean  # eBay discourages ALL CAPS
        ebay_title = next((c for c in [f"{eline} Funny {who} Sticker Vinyl Decal", f"{eline} Funny {who} Sticker",
                                       f"{eline} {who} Sticker", f"{eline} Sticker"] if len(c) <= 80),
                          eline[:80].rsplit(" ", 1)[0])
        return {
            "primary_category": {"id": primary, "path": P["path"], "slug": P["slug"]},
            "secondary_categories": [{"id": c, "path": self.nodes[c]["path"], "slug": self.nodes[c]["slug"]} for c in sec],
            "etsy_tags": tags,
            "seo_phrases": seo,
            "seo_title_template": "Funny {Who} Sticker – {line} – {HumorStyle} Decal",
            "seo_title": seo_title,
            "ebay_title": ebay_title[:80],
            "url_slug": f"{P['slug']}/" + re.sub(r"[^a-z0-9]+", "-", clean.lower()).strip("-")[:60].rstrip("-"),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--taxonomy", default=DEFAULT_TAX)
    ap.add_argument("--atlas", help="identity_atlas dir to merge")
    ap.add_argument("--write-merged-taxonomy")
    ap.add_argument("--line"); ap.add_argument("--pair", default=""); ap.add_argument("--pattern", default="")
    ap.add_argument("--darkness", type=int, default=0); ap.add_argument("--device", default="")
    ap.add_argument("--gold"); ap.add_argument("--out")
    a = ap.parse_args()
    tax = json.load(open(a.taxonomy))
    if a.atlas:
        merge_atlas(tax, load_atlas(a.atlas))
        if a.write_merged_taxonomy:
            json.dump(tax, open(a.write_merged_taxonomy, "w"), indent=1)
    T = Tagger(tax)
    if a.line:
        print(json.dumps(T.tag(a.line, a.pair, a.pattern, a.darkness, a.device), indent=1, ensure_ascii=False))
        return
    if a.gold:
        g = json.load(open(a.gold))
        out = []
        for l in g["lines"]:
            r = T.tag(l["line"], l.get("niche_pair", ""), l.get("pattern", ""), int(l.get("darkness", 0) or 0), l.get("device", ""))
            out.append({**{k: l[k] for k in ("id", "line", "niche_pair", "pattern", "darkness", "device") if k in l}, **r})
        res = {"count": len(out), "taxonomy_version": tax.get("version"), "lines": out}
        s = json.dumps(res, indent=1, ensure_ascii=False)
        if a.out:
            open(a.out, "w").write(s + "\n")
            print(f"wrote {len(out)} -> {a.out}")
        else:
            print(s)
        return
    ap.print_help(); sys.exit(1)


if __name__ == "__main__":
    main()
