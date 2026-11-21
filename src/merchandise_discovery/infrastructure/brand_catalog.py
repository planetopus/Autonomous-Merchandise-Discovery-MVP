"""Major-brand logo notes for parody stickers.

The catalog is a rotation of well-known marks. A run sees a short slice, not the whole file.
"""

import json
import zlib
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).resolve().parents[3] / "data" / "brands.json"


@lru_cache(maxsize=1)
def load_brands() -> list[dict]:
    """Load the committed brand list. An unreadable file yields no spoof targets."""

    if not _PATH.is_file():
        return []
    payload = json.loads(_PATH.read_text(encoding="utf-8"))
    rows = payload.get("brands") if isinstance(payload, dict) else payload
    brands = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())
        style = " ".join(str(item.get("style") or "").split())
        if not name or not style:
            continue
        brands.append(
            {
                "name": name,
                "category": " ".join(str(item.get("category") or "").split()),
                "style": style,
            }
        )
    return brands


def rotate_brands(brands: list[dict], seed: str, count: int = 8) -> list[dict]:
    """Return the next window of brands. A different seed advances the window."""

    if not brands or count <= 0:
        return []
    offset = zlib.adler32(seed.encode()) % len(brands)
    width = min(count, len(brands))
    return [brands[(offset + index) % len(brands)] for index in range(width)]


def brand_prompt(brands: list[dict]) -> str:
    """Tell the writer which logos to spoof in this run."""

    if not brands:
        return ""
    lines = [
        (
            "Major brand logo spoofs are optional and rare. Use brand_logo_spoof only when "
            "the brand's product, slogan, or identity is why the joke is funny. "
            "A name swap that only sticks the topic into the logo fails. "
            "Set spoof_brand and describe the logo colors and shape in image_idea. "
            "Do not reprint an anchor line."
        )
    ]
    for brand in brands:
        lines.append(f"- {brand['name']} ({brand['category']}): {brand['style']}")
    return "\n".join(lines) + "\n"


def style_for(brand: str, *hints: str) -> dict | None:
    """Find a catalog row by spoof_brand, then by a name mentioned in the line."""

    brands = load_brands()
    wanted = _norm(brand)
    if wanted:
        for item in brands:
            if _norm(item["name"]) == wanted:
                return item
    blob = _norm(" ".join(hints))
    best = None
    for item in brands:
        name = _norm(item["name"])
        if name and name in blob and (best is None or len(name) > len(_norm(best["name"]))):
            best = item
    return best


def _norm(text: str) -> str:
    return " ".join(str(text or "").casefold().replace("&", " and ").split())
