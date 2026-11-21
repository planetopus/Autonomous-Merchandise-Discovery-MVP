#!/usr/bin/env python3
"""Builds taxonomy.json (deterministic). Edit the SPEC tables below, then re-run.

Node fields: id, name, slug, path, facet, short_tag (<=20 chars, Etsy tag),
search_phrases (3-8 buyer phrases), match_terms (lowercase regex-ish words the
tagger looks for in line + niche pair), atlas_ids (identity_atlas ids, filled
later by categorize.py --atlas), children.
"""
import json, re, os

def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

# ---------------- IDENTITY: (group, [(name, singular, plural, match_terms, extra_phrases)])
I = lambda name, sing, plur, terms, extra=(): (name, sing, plur, terms, list(extra))
IDENTITY = [
 ("Family Roles", [
   I("Dads", "dad", "dads", ["dad", "dads", "father", "fathers", "daddy"], ["fathers day stickers", "dad joke sticker"]),
   I("Moms", "mom", "moms", ["mom", "moms", "mother", "mama", "mommy"], ["mom life sticker", "mothers day gift"]),
   I("Grandpas", "grandpa", "grandpas", ["grandpa", "grandpas", "grandfather", "papa"], ["grandpa gifts"]),
   I("Grandmas", "grandma", "grandmas", ["grandma", "grandmas", "grandmother", "nana", "granny"], ["grandma gifts"]),
   I("Divorced", "divorced", "divorced people", ["divorce", "divorced", "ex-wife", "ex wife", "ex-husband", "my ex", "custody"], ["divorce gifts", "funny divorce sticker"]),
   I("Widowers", "widower", "widowers", ["widow", "widower", "widowers"], []),
   I("Oldest Daughters", "oldest daughter", "oldest daughters", ["oldest daughter", "eldest daughter", "oldest daughters"], ["eldest daughter sticker"]),
   I("Boat Dads", "boat dad", "boat dads", ["boat dad", "boat dads", "boat"], ["boat sticker funny"]),
   I("Dog Moms", "dog mom", "dog moms", ["dog mom", "dog moms"], ["dog mom gifts"]),
   I("Toddler Parents", "toddler parent", "toddler parents", ["toddler", "toddlers"], ["parenting humor sticker"]),
 ]),
 ("Healthcare", [
   I("Nurses", "nurse", "nurses", ["nurse", "nurses", "nursing", "rn", "icu", "er nurse", "charge nurse", "scrubs"], ["nurse life decal", "gifts for nurses", "nurses week gifts"]),
   I("ER & Night Shift", "night shift", "night shift", ["night shift", "er ", "er techs", "full moon", "graveyard shift", "4 am", "3 am"], ["night shift nurse sticker"]),
   I("Hospice Nurses", "hospice nurse", "hospice nurses", ["hospice"], []),
   I("Paramedics & EMTs", "paramedic", "paramedics", ["paramedic", "paramedics", "emt", "ambulance"], ["emt sticker", "ems decal"]),
   I("Pharmacists", "pharmacist", "pharmacists", ["pharmacist", "pharmacists", "pharmacy"], ["pharmacy tech sticker"]),
   I("Dental Hygienists", "dental hygienist", "dental hygienists", ["dental", "hygienist", "dentist", "floss"], ["dental hygienist gifts"]),
   I("Vets & Vet Techs", "vet tech", "vet techs", ["vet ", "vets", "veterinar", "vet tech"], ["veterinarian gifts"]),
   I("Morticians", "mortician", "morticians", ["mortician", "morticians", "funeral director", "casket", "embalm"], ["funeral director gifts", "mortician humor"]),
 ]),
 ("First Responders", [
   I("Firefighters", "firefighter", "firefighters", ["firefighter", "firefighters", "fireman", "firehouse"], ["firefighter decal", "firefighter gifts"]),
   I("911 Dispatchers", "dispatcher", "dispatchers", ["dispatcher", "dispatchers", "911"], ["911 dispatcher gifts"]),
 ]),
 ("Trades & Blue Collar", [
   I("Electricians", "electrician", "electricians", ["electrician", "electricians", "shocked", "volt"], ["electrician hard hat stickers"]),
   I("Plumbers", "plumber", "plumbers", ["plumber", "plumbers", "plumbing", "drain"], ["plumber hard hat stickers"]),
   I("Mechanics", "mechanic", "mechanics", ["mechanic", "mechanics", "check engine", "wrench"], ["mechanic toolbox stickers"]),
   I("Truckers", "trucker", "truckers", ["trucker", "truckers", "four-wheeler", "18 wheeler", "cdl", "semi"], ["trucker decals", "truck driver gifts"]),
   I("Farmers", "farmer", "farmers", ["farmer", "farmers", "cows", "tractor", "farm"], ["farm life sticker"]),
   I("Construction Workers", "construction worker", "construction workers", ["construction", "hard hat", "lineman", "welder"], ["hard hat stickers funny", "construction stickers"]),
 ]),
 ("Office & Tech", [
   I("IT & Tech Support", "IT", "IT", ["it people", "it guy", "ticket", "tech support", "help desk", "printer", "turn it off"], ["tech support sticker", "IT humor stickers"]),
   I("Office Workers", "office", "office workers", ["office", "meeting", "meetings", "email", "coworker", "boss", "zoom"], ["coworker gifts", "office humor stickers"]),
   I("Accountants", "accountant", "accountants", ["accountant", "accountants", "tax season", "cpa", "spreadsheet"], ["accountant gifts", "cpa gifts"]),
   I("Programmers", "programmer", "programmers", ["programmer", "coder", "developer", "code"], ["laptop stickers programmer", "coding stickers"]),
 ]),
 ("Service & Hospitality", [
   I("Teachers", "teacher", "teachers", ["teacher", "teachers", "classroom", "hall duty", "tenure", "summer break", "students"], ["teacher life sticker", "teacher appreciation gifts", "teacher gifts"]),
   I("Librarians", "librarian", "librarians", ["librarian", "librarians", "library", "overdue"], ["librarian gifts", "book lover sticker"]),
   I("Servers & Bartenders", "server", "servers", ["server", "servers", "tip", "tippers", "waitress", "bartender"], ["waitress gifts", "restaurant humor"]),
   I("Retail Workers", "retail worker", "retail workers", ["retail", "customer", "customers", "holiday shoppers", "cashier"], ["retail worker gifts"]),
   I("Hairstylists", "hairstylist", "hairstylists", ["hairstylist", "hairstylists", "hair", "salon"], ["hair stylist gifts", "salon stickers"]),
   I("Nail Techs", "nail tech", "nail techs", ["nail tech", "nail techs", "nails", "acrylic"], ["nail tech gifts"]),
 ]),
 ("Faith & Church", [
   I("Christians", "christian", "christians", ["christ", "jesus", "god", "church", "pray", "prayer", "bible", "amen", "blessed"], ["christian stickers", "funny christian stickers", "jesus decal"]),
   I("Church Moms", "church mom", "church moms", ["church mom", "church moms", "church lady", "church ladies", "casserole", "choir"], ["church lady gifts"]),
   I("Pastors & Deacons", "pastor", "pastors", ["pastor", "pastors", "deacon", "deacons", "youth pastor", "sermon", "offering plate"], ["pastor appreciation gifts"]),
   I("Catholics", "catholic", "catholics", ["catholic", "catholics", "rosary", "mass"], ["catholic stickers"]),
   I("Homeschool Moms", "homeschool mom", "homeschool moms", ["homeschool", "essential oil"], ["homeschool mom gifts"]),
 ]),
 ("Generations & Life Stages", [
   I("Retirees", "retiree", "retirees", ["retiree", "retirees", "retired", "retirement", "senior center", "pickleball", "4:30"], ["retirement gifts", "funny retirement gifts"]),
   I("Boomers", "boomer", "boomers", ["boomer", "boomers", "ok boomer"], ["boomer stickers"]),
   I("Millennials", "millennial", "millennials", ["millennial", "millennials", "back pain", "aging", "30s", "my knees"], ["millennial humor"]),
   I("Gen Z", "gen z", "gen z", ["gen z", "rizz", "slay", "delulu", "bet", "no cap", "sigma", "skibidi"], ["gen z stickers", "brainrot stickers"]),
   I("Midlife", "midlife", "midlife", ["midlife", "over the hill", "40", "50", "cycling"], ["over the hill gifts"]),
 ]),
 ("Mental Health & Neurodivergent", [
   I("Anxiety", "anxiety", "anxiety", ["anxiety", "anxious", "panic", "panics", "phone call", "doorbell", "overthink"], ["anxiety stickers", "mental health stickers"]),
   I("ADHD", "adhd", "adhd", ["adhd", "unmedicated", "hyperfocus", "neurodivergent"], ["adhd stickers", "neurodivergent stickers"]),
   I("Depression & Therapy", "therapy", "therapy", ["depression", "depressed", "therapy", "therapist", "therapy-resistant", "coping"], ["therapy sticker", "mental health humor"]),
   I("Introverts", "introvert", "introverts", ["introvert", "introverts", "cancelled plans", "canceled plans", "stay home"], ["introvert stickers", "antisocial sticker"]),
   I("Chronic Pain", "chronic pain", "chronic pain", ["chronic pain", "chronic illness", "spoonie", "back pain"], ["chronic illness stickers", "spoonie stickers"]),
 ]),
 ("Hobbies & Outdoors", [
   I("Hunters", "hunter", "hunters", ["hunter", "hunters", "hunting", "deer", "tree stand", "buck"], ["hunting decals", "deer hunting sticker"]),
   I("Fishermen", "fisherman", "fishermen", ["fisherman", "fishermen", "fishing", "fish ", "bass", "bait"], ["fishing decals", "fishing gifts for men"]),
   I("Gardeners", "gardener", "gardeners", ["garden", "gardener", "gardeners", "tomato", "tomatoes", "plant", "plants"], ["gardening gifts", "plant lover sticker"]),
   I("Birdwatchers", "birder", "birders", ["bird", "birds", "birdwatch", "birding", "crow", "crows"], ["bird lover gifts", "crow stickers"]),
   I("Gamers", "gamer", "gamers", ["gamer", "gamers", "gaming", "backlog", "controller", "respawn", "xbox", "playstation"], ["gamer laptop stickers", "video game stickers"]),
   I("True Crime Fans", "true crime", "true crime fans", ["true crime", "murder", "dateline", "podcast", "podcasts", "serial killer"], ["true crime gifts", "murderino sticker"]),
   I("Pickleball Players", "pickleball", "pickleball players", ["pickleball"], ["pickleball gifts"]),
   I("Lawn Care Dads", "lawn", "lawn dads", ["lawn", "mow", "mowing", "grass", "yard"], ["lawn mower sticker"]),
   I("Jeep Owners", "jeep", "jeep owners", ["jeep", "jeep wave", "duck duck jeep"], ["jeep decals", "jeep stickers funny"]),
   I("Truck Owners", "truck", "truck owners", ["truck", "trucks", "diesel", "lifted"], ["truck decals funny", "truck stickers"]),
   I("Plant Parents", "plant mom", "plant parents", ["plant parent", "plant mom", "overwater", "houseplant"], ["plant mom sticker"]),
 ]),
 ("Lifestyles & Subcultures", [
   I("Recovery & Sobriety", "sober", "sober people", ["sober", "sobriety", "recovery", "aa ", "relapse", "one day at a time", "rehab"], ["sobriety stickers", "recovery stickers", "aa sticker"]),
   I("Gym Bros", "gym", "gym bros", ["gym", "swole", "deadlift", "gains", "protein", "leg day", "lift"], ["gym stickers", "gym bro gifts"]),
   I("Goths & Emo", "goth", "goths", ["goth", "goths", "emo", "black lipstick", "spooky"], ["goth stickers", "spooky goth decal"]),
   I("Stoners", "stoner", "stoners", ["stoner", "weed", "420", "high"], ["stoner stickers"]),
   I("Country & Rednecks", "redneck", "rednecks", ["redneck", "country", "hillbilly", "small town", "tractor"], ["redneck stickers", "country girl decal"]),
   I("Conservatives", "conservative", "conservatives", ["maga", "conservative", "republican", "patriot"], ["conservative stickers", "political bumper stickers"]),
   I("Liberals", "liberal", "liberals", ["liberal", "liberals", "democrat", "woke", "progressive"], ["liberal bumper stickers", "political bumper stickers"]),
   I("Redditors & Internet People", "reddit", "redditors", ["reddit", "redditor", "chronically online", "internet", "meme"], ["meme stickers", "chronically online sticker"]),
   I("Pretty Girls & Baddies", "pretty girl", "pretty girls", ["pretty girl", "hot girl", "baddie", "slay queen", "queen"], ["hot girl stickers", "baddie stickers"]),
   I("Angry & Petty People", "petty", "petty people", ["petty", "angry", "rage", "grumpy", "hate people", "gary"], ["grumpy stickers", "petty sticker", "i hate people sticker"]),
 ]),
 ("Pets & Animals", [
   I("Dog Lovers", "dog", "dog lovers", ["dog", "dogs", "puppy"], ["dog lover gifts"]),
   I("Cat Lovers", "cat", "cat lovers", ["cat", "cats", "kitty"], ["cat lover gifts", "cat stickers funny"]),
 ]),
]

# ---------------- OCCASION
OCCASIONS = [
 ("Father's Day", ["fathers day", "father's day"], ["fathers day stickers", "fathers day gifts funny", "funny gifts for dad", "dad stocking stuffers"], ["dad", "dads", "father", "grandpa"]),
 ("Mother's Day", ["mothers day"], ["mothers day gifts funny", "funny gifts for mom", "mom stickers"], ["mom", "moms", "mother", "grandma", "mama"]),
 ("Nurses Week", ["nurses week"], ["nurses week gifts", "nurse appreciation gifts", "gifts for nurses", "nurse week stickers"], ["nurse", "nurses", "nursing"]),
 ("Teacher Appreciation", ["teacher appreciation"], ["teacher appreciation gifts", "teacher gifts", "teacher stickers"], ["teacher", "teachers"]),
 ("Christmas & Stocking Stuffers", ["christmas", "santa", "stocking"], ["stocking stuffers for adults", "funny stocking stuffers", "christmas stickers", "white elephant gifts"], []),
 ("Thanksgiving", ["thanksgiving", "turkey"], ["thanksgiving stickers", "funny thanksgiving gifts", "turkey day sticker"], ["thanksgiving", "turkey"]),
 ("Halloween", ["halloween", "spooky"], ["halloween stickers", "spooky stickers", "funny halloween decals"], ["halloween", "spooky", "casket", "coffin"]),
 ("Birthday", ["birthday"], ["funny birthday gifts", "birthday gag gifts", "gag gifts for adults"], ["birthday"]),
 ("Retirement", ["retirement", "retired"], ["retirement gifts", "funny retirement gifts", "retirement gag gifts"], ["retire", "retired", "retirees", "retirement"]),
 ("Divorce Party", ["divorce party"], ["divorce gifts", "divorce party gifts", "funny divorce gifts"], ["divorce", "divorced", "my ex", "ex-wife"]),
 ("White Elephant & Gag Gifts", ["gag gift", "white elephant"], ["white elephant gifts", "gag gifts", "funny gag gifts"], []),
 ("Graduation & New Job", ["graduation"], ["nursing school graduation gifts", "new job gifts", "graduation gifts funny"], ["graduat"]),
 ("Sobriety Anniversary", ["sobriety"], ["sobriety gifts", "recovery gifts", "sober anniversary gift"], ["sober", "sobriety", "recovery"]),
]

# ---------------- HUMOR STYLE  (name, match by pattern ids / device / darkness)
HUMOR = [
 ("Dark Humor", ["dark humor stickers", "dark humor decals", "morbid stickers", "gallows humor gifts", "dark humor gifts"], {"darkness_min": 2}),
 ("Sarcastic", ["sarcastic stickers", "sarcastic bumper stickers", "sarcastic gifts", "sarcasm decal"], {"device": "sarcasm", "patterns": ["deadpan_sarcasm", "cheerful_dark_label"]}),
 ("Ironic & Absurd", ["ironic stickers", "absurd stickers", "weird stickers", "random funny stickers"], {"device": "irony", "patterns": ["situational_irony", "brand_new_sentence", "oddly_specific_vibe"]}),
 ("Oddly Specific", ["oddly specific stickers", "oddly specific gifts", "weirdly specific sticker"], {"patterns": ["oddly_specific_vibe", "true_identity_stack", "club_roster"]}),
 ("Relatable & Wholesome", ["relatable stickers", "wholesome stickers", "cute funny stickers"], {"darkness_max": 0}),
 ("Adult Humor", ["adult humor stickers", "inappropriate stickers", "adult bumper stickers", "naughty stickers"], {"terms": ["naked", "sex", "thicc", "milf", "zaddy", "erection", "booty", "big back", "rizz"]}),
 ("Meme & Gen Z Slang", ["meme stickers", "gen z stickers", "brainrot stickers", "meme decals"], {"terms": ["rizz", "rizzless", "sigma", "delulu", "slay", "era", "main character", "bet", "no cap", "yapper", "highly regarded", "boujee", "feral", "unhinged"]}),
 ("Fake Warning Signs", ["funny warning stickers", "warning sign stickers", "caution sticker funny", "funny caution decal"], {"patterns": ["official_warning_sign", "self_defeating_sign"]}),
 ("Self-Deprecating", ["self deprecating stickers", "self roast sticker", "funny honest stickers"], {"patterns": ["insider_deadpan_confession", "economy_downgrade", "clinical_life_report", "unfair_comparison_gripe"]}),
 ("Fake Credentials & Awards", ["funny award stickers", "certified sticker funny", "achievement stickers"], {"patterns": ["fake_credential"]}),
]

# ---------------- PRODUCT USE
PRODUCT = [
 ("Laptop Stickers", ["laptop stickers", "funny laptop stickers", "laptop decals", "vinyl laptop stickers"], ["laptop", "code", "email", "office"]),
 ("Bumper Stickers & Car Decals", ["funny bumper stickers", "car decals funny", "bumper sticker", "funny car stickers", "truck window decal"], ["truck", "car", "jeep", "honk", "drive", "driver", "gps", "road", "four-wheeler", "recall"]),
 ("Water Bottle Stickers", ["water bottle stickers", "funny water bottle stickers", "hydro flask stickers", "tumbler decal"], ["coffee", "water", "drink", "hydrat", "nurse", "teacher", "gym"]),
 ("Hard Hat Stickers", ["hard hat stickers", "funny hard hat stickers", "hard hat decals", "construction helmet sticker"], ["electrician", "plumber", "lineman", "welder", "construction", "hard hat"]),
 ("Toolbox Stickers", ["toolbox stickers", "mechanic stickers", "tool box decals", "garage stickers"], ["mechanic", "garage", "tool", "wrench", "home depot", "check engine"]),
 ("Badge Reel & Scrubs Stickers", ["badge reel stickers", "nurse badge sticker", "clipboard stickers"], ["nurse", "nurses", "er ", "hospital", "shift", "paramedic", "pharmac"]),
 ("Cooler & Tackle Box Stickers", ["cooler stickers", "yeti stickers", "tackle box stickers"], ["fishing", "fisherman", "hunting", "hunter", "boat", "beer", "camping"]),
 ("Phone & Kindle Stickers", ["phone stickers", "kindle stickers", "small funny stickers"], ["book", "library", "librarian", "reading", "kindle"]),
]

# ---------------- TOPIC
TOPIC = [
 ("Coffee", ["coffee", "caffeine", "espresso", "latte", "frappe"], ["funny coffee stickers", "coffee lover gifts", "coffee decal"]),
 ("BBQ & Grilling", ["bbq", "brisket", "smoker", "grill", "grilling", "smoke"], ["bbq stickers", "grilling gifts for men", "bbq decal", "smoker sticker"]),
 ("Trucks & Cars", ["truck", "trucks", "car", "cars", "jeep", "engine", "recall", "payment"], ["truck decals funny", "car guy gifts", "funny car decals"]),
 ("Fishing", ["fishing", "fish", "bass", "fisherman", "fishermen"], ["fishing stickers", "fishing decals funny", "fishing gifts"]),
 ("Hunting", ["hunting", "hunter", "hunters", "deer"], ["hunting stickers", "deer hunting decals"]),
 ("Anxiety & Mental Health", ["anxiety", "panic", "therapy", "depression", "mental"], ["anxiety stickers", "mental health stickers", "therapy stickers"]),
 ("Wine & Drinking", ["wine", "beer", "drink", "drunk", "margarita"], ["wine stickers", "funny wine gifts", "drinking stickers"]),
 ("Sleep & Exhaustion", ["sleep", "tired", "exhaust", "nap", "4 am", "3 am", "night shift"], ["tired mom sticker", "sleep deprived gifts"]),
 ("True Crime & Murder Podcasts", ["true crime", "murder", "dateline", "podcast"], ["true crime stickers", "murder podcast gifts", "true crime decals"]),
 ("Death & Funerals", ["death", "funeral", "casket", "dnr", "die", "grave", "coffin", "dead"], ["funeral humor", "death stickers funny", "morbid gifts"]),
 ("Money & Debt", ["debt", "bank", "payment", "broke", "afford", "paid off", "tip", "layaway", "economy"], ["broke stickers", "funny money decal"]),
 ("Food & Snacks", ["food", "chili", "burrito", "lunch", "fast food", "applebee", "leftover", "candy", "casserole", "snack"], ["food stickers funny", "snack stickers"]),
 ("Aging & Back Pain", ["aging", "back pain", "knees", "old", "senior", "hip"], ["getting old stickers", "over the hill stickers"]),
 ("Work & Jobs", ["shift", "work", "job", "boss", "meeting", "ticket", "customer", "clock in"], ["work humor stickers", "coworker gifts funny"]),
 ("Family Drama & Holidays", ["thanksgiving", "family", "holiday", "christmas", "in-laws", "thermostat"], ["family humor stickers", "funny family gifts"]),
 ("Church & Faith", ["church", "jesus", "christ", "pray", "god", "bible", "sermon", "deacon", "choir"], ["christian stickers funny", "church humor"]),
 ("Gardening & Plants", ["garden", "tomato", "plant", "plants", "grass", "lawn"], ["gardening stickers", "plant stickers funny"]),
 ("Birds & Animals", ["bird", "crow", "cow", "cows", "dog", "cat", "animal", "deer"], ["animal stickers funny", "crow stickers"]),
 ("Gaming", ["game", "gaming", "gamer", "backlog", "controller"], ["gaming stickers", "gamer decals"]),
 ("Shopping & Online Orders", ["amazon", "cart", "online shopping", "package", "target"], ["shopping addict sticker", "amazon prime humor"]),
]

FACET_ROOTS = [
 ("identity", "Who It's For", ["funny stickers", "funny gifts for him", "funny gifts for her", "job stickers funny"]),
 ("occasion", "Occasion & Gift", ["funny gift stickers", "gag gifts", "stocking stuffers for adults"]),
 ("humor", "Humor Style", ["funny stickers", "funny decals", "funny vinyl stickers"]),
 ("product", "Use It On", ["vinyl stickers", "waterproof stickers", "vinyl decals"]),
 ("topic", "Topic", ["novelty stickers", "funny decals", "funny sticker pack"]),
]

def short(s):
    s = s.lower().replace("&", "and").replace("'", "")
    return s if len(s) <= 20 else s[:20].rsplit(" ", 1)[0]

def uniq(xs):
    out = []
    for x in xs:
        x = re.sub(r"\s+", " ", x.strip().lower())
        if x and x not in out:
            out.append(x)
    return out

def node(nid, name, facet, path, phrases, terms, **kw):
    base = re.sub(r"[^a-z0-9 ]", "", name.lower().replace("&", " ")).split()
    base = " ".join(base)
    phrases = uniq(phrases)
    if len(phrases) < 3:  # pad thin nodes with generic buyer phrasings
        phrases = uniq(phrases + [f"funny {base} stickers", f"{base} decals", f"{base} gifts"])
    phrases = phrases[:8]
    assert len(phrases) >= 3, (name, phrases)
    st = next((p for p in phrases if len(p) <= 20), None) if facet != "identity" else None
    d = {"id": nid, "name": name, "slug": slug(name), "path": path, "facet": facet,
         "short_tag": st or short(name), "search_phrases": phrases,
         "match_terms": uniq(terms)}
    d.update(kw)
    d["children"] = []
    return d

def build():
    roots = []
    for fid, fname, fph in FACET_ROOTS:
        roots.append(node(fid, fname, fid, fname, fph, []))
    R = {r["id"]: r for r in roots}
    # identity
    for gname, items in IDENTITY:
        g = node(f"identity/{slug(gname)}", gname, "identity", f"Who It's For > {gname}",
                 [it[3][0] and f"funny {it[1]} stickers" for it in items][:6], [])
        for name, sing, plur, terms, extra in items:
            ph = [f"funny {sing} stickers", f"gifts for {plur}", f"{sing} life sticker",
                  f"funny {sing} decal", f"{sing} bumper sticker"] + extra
            # put curated extras early so they survive the 8 cap
            ph = ph[:2] + extra + ph[2:]
            c = node(f"{g['id']}/{slug(name)}", name, "identity", f"{g['path']} > {name}", ph, terms,
                     singular=sing, plural=plur, short_tag=short(f"{sing} sticker"), atlas_ids=[])
            g["children"].append(c)
        R["identity"]["children"].append(g)
    for name, terms, ph, ident in OCCASIONS:
        R["occasion"]["children"].append(node(f"occasion/{slug(name)}", name, "occasion",
            f"Occasion & Gift > {name}", ph, terms, identity_triggers=uniq(ident)))
    for name, ph, rule in HUMOR:
        R["humor"]["children"].append(node(f"humor/{slug(name)}", name, "humor",
            f"Humor Style > {name}", ph, rule.get("terms", []), rule={k: v for k, v in rule.items() if k != "terms"}))
    for name, ph, terms in PRODUCT:
        R["product"]["children"].append(node(f"product/{slug(name)}", name, "product",
            f"Use It On > {name}", ph, terms))
    for name, terms, ph in TOPIC:
        R["topic"]["children"].append(node(f"topic/{slug(name)}", name, "topic",
            f"Topic > {name}", ph, terms))
    return roots

def walk(ns):
    for n in ns:
        yield n
        yield from walk(n["children"])

if __name__ == "__main__":
    roots = build()
    allnodes = list(walk(roots))
    ids = [n["id"] for n in allnodes]
    assert len(ids) == len(set(ids))
    counts = {r["facet"]: sum(1 for n in walk([r])) - 1 for r in roots}
    out = {"version": 1, "generated_by": "build_taxonomy.py",
           "facets": [r["id"] for r in roots], "node_counts": counts,
           "total_nodes": len(allnodes), "tree": roots}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "taxonomy.json")
    json.dump(out, open(p, "w"), indent=1)
    print(counts, len(allnodes))
