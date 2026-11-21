"""Categorize a kept sticker line with the taxonomy tagger and the identity atlas.

The tagger is deterministic. One process builds it once, with data/identity_atlas merged
in, and reuses it for every final candidate.
"""

import importlib.util
import json
from functools import lru_cache
from pathlib import Path

from merchandise_discovery.infrastructure.humor_reference_loader import humor_csv_search_starts


def _find(*parts: str) -> Path | None:
    for start in humor_csv_search_starts():
        current = start if start.is_dir() else start.parent
        for _ in range(10):
            candidate = current.joinpath(*parts)
            if candidate.exists():
                return candidate
            if current.parent == current:
                break
            current = current.parent
    return None


def _categorize_module():
    path = _find("scripts", "categorize.py")
    if path is None:
        raise FileNotFoundError("scripts/categorize.py was not found")
    spec = importlib.util.spec_from_file_location("merch_categorize", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError("scripts/categorize.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def get_tagger():
    """Build the atlas-merged tagger. Missing files raise so a run does not invent categories."""

    module = _categorize_module()
    taxonomy_path = _find("data", "categories", "taxonomy.json")
    atlas_dir = _find("data", "identity_atlas")
    if taxonomy_path is None or atlas_dir is None:
        raise FileNotFoundError("Category taxonomy or identity atlas was not found")
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    module.merge_atlas(taxonomy, module.load_atlas(str(atlas_dir)))
    return module.Tagger(taxonomy)


def categorize_line(text: str, niche_pair: str = "", pattern: str = "", device: str = "") -> dict:
    """Return shop fields for one line. eBay titles stay within 80 characters."""

    tagged = get_tagger().tag(text or "", niche_pair or "", pattern or "", 0, device or "")
    secondary = [item.get("path") or "" for item in tagged.get("secondary_categories") or []]
    primary = tagged.get("primary_category") or {}
    ebay = str(tagged.get("ebay_title") or "")[:80]
    return {
        "main_category": primary.get("path") or "",
        "secondary_categories": [item for item in secondary if item],
        "tags": list(tagged.get("etsy_tags") or []),
        "website_title": tagged.get("seo_title") or "",
        "ebay_title": ebay,
        "slug": tagged.get("url_slug") or "",
    }


def attach_categories(payload: dict) -> dict:
    """Stamp every final candidate. A tagger failure leaves the lines uncategorized."""

    candidates = payload.get("candidates") or []
    pair = " x ".join(
        part
        for part in (str(payload.get("niche_pair_a") or ""), str(payload.get("niche_pair_b") or ""))
        if part.strip()
    )
    try:
        stamped = [
            categorize_line(
                str(candidate.get("artwork_text") or ""),
                pair,
                str(candidate.get("pattern") or ""),
                str(candidate.get("comic_turn") or ""),
            )
            if isinstance(candidate, dict)
            else {}
            for candidate in candidates
        ]
    except (OSError, ValueError, KeyError, FileNotFoundError):
        return payload
    for candidate, fields in zip(candidates, stamped, strict=False):
        if isinstance(candidate, dict):
            candidate.update(fields)
    return payload
