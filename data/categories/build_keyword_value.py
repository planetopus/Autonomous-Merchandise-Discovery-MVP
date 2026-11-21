#!/usr/bin/env python3
"""Builds keyword_value.csv from measured evidence only. Never fills numbers it did not measure."""
import csv, json, os, re
EBAY = "evidence/ebay_browse.jsonl"           # rows written only if the eBay Browse API calls succeed
GAC = "evidence/google_autocomplete.jsonl"
phrases = json.load(open("evidence/phrases.json"))
gac = {}
if os.path.exists(GAC):
    for l in open(GAC):
        r = json.loads(l); gac[r["phrase"]] = r
ebay = {}
if os.path.exists(EBAY):
    for l in open(EBAY):
        r = json.loads(l); ebay[r["phrase"]] = r

def variants(p):
    v = {p}
    v.add(re.sub(r"stickers\b", "sticker", p)); v.add(re.sub(r"sticker\b", "stickers", p))
    v.add(re.sub(r"decals\b", "decal", p)); v.add(re.sub(r"decal\b", "decals", p))
    v.add(re.sub(r"gifts\b", "gift", p)); v.add(re.sub(r"gift\b", "gifts", p))
    return v

PHYS = re.compile(r"\b(car|cars|truck|trucks|bumper|water bottle|hydro|tumbler|laptop|hard hat|helmet|cooler|yeti|boat|boats|"
                  r"window|vinyl|decal|decals|amazon|etsy|near me|walmart|target|toolbox|tool box|wall|kindle|for (men|women|him|her|adults|work))\b")
DIGI = re.compile(r"\b(imessage|iphone|whatsapp|discord|png|telegram|snapchat|copy and paste|emoji|tiktok|gif|messages|signal|free|printable|clipart|svg|on face)\b")
rows = []
for p, path in phrases:
    g = gac.get(p); e = ebay.get(p)
    exact = ext = phys = digi = None; top = ""
    if g:
        s = [x.lower() for x in g["suggestions"]]
        V = variants(p)
        exact = any(x in V for x in s)
        ext = sum(1 for x in s if any(x.startswith(v + " ") for v in V))
        top = " | ".join(g["suggestions"][:6])
        def rest(x):  # only judge the words a shopper ADDED to the phrase
            for v in sorted(V, key=len, reverse=True):
                if x.startswith(v):
                    return x[len(v):]
            return x
        phys = sum(1 for x in s if PHYS.search(rest(x))); digi = sum(1 for x in s if DIGI.search(rest(x)))
    if g is None and e is None:
        tier, why = "unmeasured", "No measurement collected for this phrase."
    elif g is not None:
        n = len(g["suggestions"])
        if exact and ext >= 6 and (digi or 0) <= (phys or 0):
            tier = "high"
        elif exact or ext >= 3:
            tier = "med"
        else:
            tier = "low"
        why = (f"Google autocomplete (US) {'returns this phrase (or its singular/plural)' if exact else 'does NOT return this phrase'}"
               f" plus {ext} longer suggestions built on it ({n} suggestions total). "
               + ("Many long-tail extensions = shoppers actively type this." if ext >= 6 else
                  "Some long-tail extensions = moderate demand." if ext >= 3 else
                  "Few/no extensions = weak or niche demand." if n else "Zero suggestions = no detectable demand.")
               + f" {phys} suggestions point to physical products (car, water bottle, laptop, hard hat, Amazon/Etsy...)"
               + f", {digi} to digital/messaging stickers (iMessage, WhatsApp, PNG...)"
               + ("; downgraded because digital intent dominates." if exact and ext >= 6 and digi > phys else ".")
               + " Autocomplete shows demand exists, not volume; competition not measured.")
    src = []
    if e: src.append("eBay Browse API item_summary/search (EBAY_US)")
    if g: src.append(f"Google autocomplete suggestqueries client=firefox hl=en gl=us, fetched {g['fetched_at']}")
    rows.append({
        "phrase": p, "category_path": path,
        "ebay_active_listings": e["total"] if e and e.get("total") is not None else "",
        "avg_price_if_available": e["avg_price"] if e and e.get("avg_price") is not None else "",
        "evidence_source": "; ".join(src) if src else "unmeasured",
        "ebay_status": "measured" if e else "unmeasured",
        "google_autocomplete_exact": "" if exact is None else ("yes" if exact else "no"),
        "google_autocomplete_extensions": "" if ext is None else ext,
        "google_physical_product_suggestions": "" if phys is None else phys,
        "google_digital_sticker_suggestions": "" if digi is None else digi,
        "google_top_suggestions": top,
        "buyer_intent": "sticker/decal" if re.search(r"sticker|decal", p) else "gift/broad",
        "value_tier": tier,
        "reasoning": why,
    })
order = {"high": 0, "med": 1, "low": 2, "unmeasured": 3}
rows.sort(key=lambda r: (order[r["value_tier"]], r["buyer_intent"] != "sticker/decal",
                         -(r["google_physical_product_suggestions"] or 0), -(r["google_autocomplete_extensions"] or 0), r["phrase"]))
with open("keyword_value.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
from collections import Counter
print(Counter(r["value_tier"] for r in rows), len(rows))
