# Identity Atlas + Slang Lexicon + Overlap Combos

Data only. No app code reads these files yet.

**Humor theory (from Ant):** people break into groups, subgroups, and stereotypes, and stereotypes exist because they come from truth. The best line names a real overlapping identity truthfully, in words the group wouldn't use about itself. Gen Z or Gen Alpha slang on an older or wholesome group works especially well. The target reads it, thinks "haha, that's me", and buys it. Model line: *THICC DADS WHO VAPE FOR CHRIST*.

| File | What it holds |
|---|---|
| `identity_atlas.json` | 534 subgroups in 38 top-level groups. Each subgroup has true traits (5–10), self terms vs outsider terms, `never_use_terms`, overlaps (subgroup ids), `buyer_pride` (1–10), `dark_tolerance` (0–3), `ownership_only`, and a `source` note |
| `slang_lexicon.json` | 181 terms. Each has a meaning, register (Gen Z / Alpha), `funny_mismatch_score`, `example_pattern`, `status`, a `dated_or_cringe` flag, `use_on_merch`, and sources |
| `overlap_combos.json` | 170 real 2–3-way overlaps. Each has the shared truth, a slang hook, a pattern, and one original example line |
| `src/` | Hand-written source rows plus `build.py`. Edit the rows, then run `python3 src/build.py` from `src/` to regenerate the JSON |

## How the engine should use it
1. Pick a combo, or pick a subgroup and walk its `overlaps`, so you get 2–3 identities that genuinely co-occur in one person.
2. Take one or two true traits from each identity.
3. Add a slang term with a high `funny_mismatch_score`. Dated or cringe terms are funny on purpose when an older group says them sincerely.
4. Fit the line to a pattern (`pattern_guide` in `overlap_combos.json`).
5. Test: would a real member say "that's me" and wear it? Prefer `buyer_pride` ≥ 8.

## Guardrails
- Affectionate, self-ownable humor only. No slurs. `never_use_terms` lists outsider insults.
- Subgroups with `ownership_only: true` (heritage, disability, LGBTQ+, serious illness) are written only in the in-group's own pride voice, never as an outsider's punchline.
- Keep it marketplace-safe for Etsy, eBay, and Redbubble. Skip terms where `use_on_merch` is false (crude ones).

## Sources and limits
- Fetched this run at human pace (one page at a time, at least 8 s apart):
  - Wikipedia's *Glossary of 2020s slang* and *List of subcultures*
  - Redbubble funny-sticker searches (general, bumper, dad, mom, job, hobby)
  - Urban Dictionary pages: no cap, NPC, highkey, era, -core, delulu, mogging, looksmaxxing, the ick, unc
  - Know Your Meme pages: fanum tax, mewing
  - The R&D bot's Reddit tagline list
- Blocked with 403, so not used: Reddit JSON, Etsy search, eBay search. I stopped at the first block on each.
- `subreddit community … exists` in a source note means the community is a known self-ID hub. It was not fetched this run.
- Some slang entries say "common usage; not fetched". Spot-check those before relying on them.
