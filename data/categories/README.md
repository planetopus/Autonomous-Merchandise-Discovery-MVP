# Sticker keyword categories

This folder turns each line the concept engine writes into **searchable shop categories and buyer keywords**,
so a line can go straight onto planetopus.com and eBay with the right category, tags and title.

| File | What it is |
|---|---|
| `taxonomy.json` | Category tree shoppers browse/search. 5 facets: **Who It's For** (identity), **Occasion & Gift**, **Humor Style**, **Use It On** (product), **Topic**. Every node has `slug`, `path`, `short_tag` (<=20 chars), 3-8 `search_phrases`, and `match_terms` the tagger uses. Identity nodes also carry `atlas_ids`. |
| `build_taxonomy.py` | Source of truth for the tree. Edit the tables, run it, it rewrites `taxonomy.json`. |
| `keyword_value.csv` | ~240 key search phrases with **measured** demand evidence and a value tier (see below). |
| `build_keyword_value.py`, `select_phrases.py`, `measure_google_ac.py`, `evidence/` | How the CSV was produced (run from `data/categories/`) (raw evidence kept in `evidence/*.jsonl`). |
| `scripts/categorize.py` | Deterministic tagger (no network, no randomness). |
| `gold_lines_categorized.json` | `categorize.py` run on all 200 humor-lab gold lines. |

## Tagger

```bash
python scripts/categorize.py --line "WARNING: OFF-DUTY NURSE. DO NOT SHOW ME YOUR RASH." \
    --pair "nurses x off-duty" --pattern official_warning_sign --darkness 0 --device irony
python scripts/categorize.py --gold data/humor_lab/gold_lines.json --out data/categories/gold_lines_categorized.json
# merge the identity atlas (JSON list of {id,label,group,self_terms}, or its src/sg/*.txt pipe rows):
python scripts/categorize.py --atlas path/to/identity_atlas --write-merged-taxonomy /tmp/taxonomy_merged.json --gold ...
```

Output per line:
- `primary_category`: the identity the joke is for (from niche A of the pair, then the line text); falls back to a topic.
- `secondary_categories` (3-6): second identity if strong, topic, humor style, occasion, product placement.
- `etsy_tags` (10-13, each <=20 chars): ready for Etsy's 13-tag field and as website tags.
- `seo_phrases`: longer buyer phrases from the matched nodes, for page meta/description and eBay item specifics.
- `seo_title`: `Funny {Who} Sticker – {line} – {HumorStyle} Decal` (<=140 chars, website/Etsy).
- `ebay_title`: <=80 chars (eBay's limit), ALL-CAPS lines converted to Title Case.
- `url_slug`: `{primary-slug}/{line-slug}`.

Same input + same taxonomy = same output, so results are diffable and re-runnable.

### Identity atlas
The atlas was still being built when this was written. `--atlas` accepts it later without a schema change:
matching atlas identities get their `atlas_ids` and self-terms added to the existing node; new ones become new
nodes under `Who It's For > {atlas group}` with auto-generated buyer phrases. Tested on the in-progress atlas
source rows: 470 new identity nodes, 59 attached to existing ones.

## How the engine should use it
1. After the critic keeps a line, call `Tagger(tax).tag(line, niche_pair, pattern, darkness, device)` and store
   the result on the concept document (`categories`, `tags`, `seo_title`, `ebay_title`, `url_slug`).
2. Prefer niche pairs whose identity node has `high`/`med` phrases in `keyword_value.csv` when choosing what to write.
3. Unknown identity? Add it to `build_taxonomy.py` (or let the atlas merge add it) and rebuild.

## How the website should use it
- Build browse menus from the 5 facet roots; each node's `slug` is its URL (`/stickers/who/nurses`,
  `/stickers/occasion/nurses-week`, `/stickers/humor/dark-humor`, `/stickers/use/hard-hat-stickers` ...).
- Put a product under its primary + all secondary category pages.
- Use the node's `search_phrases` for category page H1/meta, and each product's `etsy_tags` + `seo_phrases`
  for on-site search synonyms.

## keyword_value.csv: what is and isn't measured
- `google_autocomplete_*`: measured on 2026-11-21 from Google's public autocomplete (US English), one request every
  7-9 seconds. `exact` = Google suggests this phrase (or its singular/plural); `extensions` = how many of the 10
  suggestions are longer phrases built on it. This shows people actively search it, **not** how many.
- `ebay_active_listings`, `avg_price_if_available`: **blank / `unmeasured`**. The eBay API connector failed on every call
  (`Failed to get operation=[search] from specTitle=[Browse API]`, also for the Taxonomy API), so no eBay counts were
  recorded. No eBay pages were scraped. Re-run with a working Browse API: write
  `{"phrase","total","avg_price"}` rows to `evidence/ebay_browse.jsonl` and rerun `build_keyword_value.py`.
- `value_tier`: high = exact + >=6 extensions; med = exact or >=3 extensions; low = otherwise; `unmeasured` = no data.
  `buyer_intent` separates sticker/decal phrases from broad gift phrases (broad gift terms are high-demand but
  far more competitive and less sticker-specific).
