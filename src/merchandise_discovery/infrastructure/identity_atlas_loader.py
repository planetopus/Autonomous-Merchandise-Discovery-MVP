"""Optional identity atlas published by a separate job.

When data/identity_atlas/ is present, niche picking samples real overlaps
weighted by buyer-pride, and the draft and critic see traits, slang, and
self-ownability notes. A missing folder leaves the current prompts unchanged.
"""

import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from merchandise_discovery.infrastructure.humor_reference_loader import humor_csv_search_starts

_NAME_KEYS = ("name", "label", "subgroup", "identity", "id", "title")
_LIST_KEYS = {
    "traits": ("traits", "true_traits", "trueTraits"),
    "self_words": ("self_words", "selfWords", "insider_words", "words_they_use"),
    "outsider_words": ("outsider_words", "outsiderWords", "words_outsiders_use"),
    "overlaps": ("overlaps", "co_occurrences", "cooccurrences", "co_occurring", "overlaps_with"),
}


@dataclass
class IdentitySubgroup:
    """One atlas subgroup, with only the fields the prompts actually use."""

    name: str
    parent: str = ""
    dimension: str = ""
    traits: list[str] = field(default_factory=list)
    self_words: list[str] = field(default_factory=list)
    outsider_words: list[str] = field(default_factory=list)
    overlaps: list[str] = field(default_factory=list)
    buyer_pride: float = 1.0
    dark_tolerance: float = 5.0
    self_ownable: str = ""


@dataclass
class SlangTerm:
    """A younger-register word and how far it sits from the group's own voice."""

    term: str
    meaning: str = ""
    register: str = ""
    mismatch_score: float = 0.0


@dataclass
class OverlapCombo:
    """A real two- or three-way overlap, not a random stack of labels."""

    names: list[str]
    shared_detail: str = ""
    slang_hook: str = ""
    buyer_pride: float = 0.0


@dataclass
class IdentityAtlas:
    """Loaded atlas files, or empty lists when the folder is absent."""

    subgroups: list[IdentitySubgroup] = field(default_factory=list)
    slang: list[SlangTerm] = field(default_factory=list)
    combos: list[OverlapCombo] = field(default_factory=list)

    def lookup(self, name: str) -> IdentitySubgroup | None:
        """Match a user or model name to one subgroup, ignoring case and extra words."""

        key = name.casefold().strip()
        if not key:
            return None
        exact = [item for item in self.subgroups if item.name.casefold() == key]
        if exact:
            return exact[0]
        partial = [
            item
            for item in self.subgroups
            if item.name.casefold() in key or key in item.name.casefold()
        ]
        return partial[0] if partial else None


def find_identity_atlas_dir(starts: list[Path] | None = None) -> Path | None:
    """Find data/identity_atlas by walking up from the app and the working directory."""

    seen: set[str] = set()
    for start in starts if starts is not None else humor_csv_search_starts():
        current = start if start.is_dir() else start.parent
        for _ in range(10):
            key = str(current)
            if key in seen:
                break
            seen.add(key)
            candidate = current / "data" / "identity_atlas"
            if candidate.is_dir() and any(candidate.iterdir()):
                return candidate
            if current.parent == current:
                break
            current = current.parent
    return None


def load_identity_atlas(directory: Path | None = None) -> IdentityAtlas:
    """Read the atlas directory when it exists. A missing directory is an empty atlas."""

    folder = directory if directory is not None else find_identity_atlas_dir()
    if folder is None or not folder.is_dir():
        return IdentityAtlas()
    return IdentityAtlas(
        subgroups=_read_subgroups(folder / "identity_atlas.json"),
        slang=_read_slang(folder / "slang_lexicon.json"),
        combos=_read_combos(folder / "overlap_combos.json"),
    )


def split_identity_names(*fields: str) -> list[str]:
    """Split one or many identities from the niche fields. Commas, semicolons, and newlines count."""

    names: list[str] = []
    seen: set[str] = set()
    for field_value in fields:
        for part in re.split(r"[,;\n|]+", field_value or ""):
            name = " ".join(part.split())
            key = name.casefold()
            if name and key not in seen:
                names.append(name)
                seen.add(key)
    return names


def sample_overlap_pairs(
    atlas: IdentityAtlas,
    *,
    anchor: str = "",
    limit: int = 10,
    rng: random.Random | None = None,
) -> list[dict]:
    """Sample real overlaps, weighted by buyer-pride, for the niche-pair call."""

    if not atlas.subgroups and not atlas.combos:
        return []
    chooser = rng or random.Random()
    weighted: list[tuple[float, dict]] = []
    seen: set[tuple[str, str]] = set()
    anchor_key = anchor.casefold().strip()

    def add(weight: float, names: list[str], detail: str = "", hook: str = "") -> None:
        cleaned = [name.strip() for name in names if name and name.strip()]
        if len(cleaned) < 2:
            return
        if anchor_key and not any(anchor_key in name.casefold() or name.casefold() in anchor_key for name in cleaned):
            return
        key = tuple(sorted(name.casefold() for name in cleaned))
        if key in seen:
            return
        seen.add(key)
        weighted.append(
            (
                max(weight, 0.1),
                {
                    "niche_a": cleaned[0],
                    "niche_b": " + ".join(cleaned[1:]),
                    "shared_detail": detail,
                    "slang_hook": hook,
                },
            )
        )

    for combo in atlas.combos:
        pride = combo.buyer_pride or _average_pride(atlas, combo.names)
        add(pride, combo.names, combo.shared_detail, combo.slang_hook)
    for subgroup in atlas.subgroups:
        for other in subgroup.overlaps:
            partner = atlas.lookup(other)
            pride = subgroup.buyer_pride
            if partner is not None:
                pride = (subgroup.buyer_pride + partner.buyer_pride) / 2
            add(pride, [subgroup.name, other])
    if not weighted:
        return []
    picked = _weighted_sample(weighted, limit, chooser)
    return [item for _, item in picked]


def subgroup_context(atlas: IdentityAtlas, *names: str) -> tuple[list[IdentitySubgroup], list[SlangTerm]]:
    """Return the named subgroups and the highest-mismatch slang to show the writer."""

    groups = []
    seen: set[str] = set()
    for name in names:
        group = atlas.lookup(name)
        if group is None or group.name.casefold() in seen:
            continue
        groups.append(group)
        seen.add(group.name.casefold())
    ranked = sorted(atlas.slang, key=lambda item: (-item.mismatch_score, item.term.casefold()))
    return groups, ranked[:8]


def atlas_prompt(groups: list[IdentitySubgroup], slang: list[SlangTerm]) -> str:
    """Traits and mismatched slang for the draft. Empty when the atlas did not match."""

    if not groups and not slang:
        return ""
    lines = [
        (
            "Identity atlas. Use the true traits. The slang is a younger register the group "
            "would not use about themselves. Do not invent a random combo."
        )
    ]
    for group in groups:
        bits = [group.name]
        if group.dimension or group.parent:
            bits.append(f"({group.dimension or group.parent})")
        if group.traits:
            bits.append("traits: " + "; ".join(group.traits[:6]))
        if group.self_words:
            bits.append("words they use: " + ", ".join(group.self_words[:4]))
        if group.outsider_words:
            bits.append("outsider words: " + ", ".join(group.outsider_words[:4]))
        bits.append(f"buyer-pride {group.buyer_pride:g}, dark tolerance {group.dark_tolerance:g}")
        if group.self_ownable:
            bits.append(f"self-ownable: {group.self_ownable}")
        lines.append("- " + ". ".join(bits))
    if slang:
        lines.append("High-mismatch slang, 5 to 8 terms. Use at most one, and only if it fits:")
        for term in slang[:8]:
            lines.append(
                f"- {term.term} ({term.register or 'younger register'}, mismatch {term.mismatch_score:g}): "
                f"{term.meaning}"
            )
    return "\n".join(lines) + "\n"


def self_ownable_block(groups: list[IdentitySubgroup]) -> str:
    """Tell the critic when a member can claim the joke, using each subgroup's note."""

    notes = [group for group in groups if group.self_ownable]
    if not notes:
        return ""
    lines = [
        (
            "Self-ownability. Score sticker_buy_score under 7 when the line violates these notes. "
            "A member must be able to say 'that's me' without the joke punching down."
        )
    ]
    for group in notes:
        lines.append(f"- {group.name}: {group.self_ownable}")
    return "\n".join(lines) + "\n"


def _read_subgroups(path: Path) -> list[IdentitySubgroup]:
    rows = _rows(path, "subgroups", "identities", "groups", "items")
    groups = []
    for item in rows:
        name = _text(item, *_NAME_KEYS)
        if not name:
            continue
        groups.append(
            IdentitySubgroup(
                name=name,
                parent=_text(item, "parent", "group", "category"),
                dimension=_text(item, "dimension", "axis", "type"),
                traits=_texts(item, *_LIST_KEYS["traits"]),
                self_words=_texts(item, *_LIST_KEYS["self_words"]),
                outsider_words=_texts(item, *_LIST_KEYS["outsider_words"]),
                overlaps=_texts(item, *_LIST_KEYS["overlaps"]),
                buyer_pride=_number(item, 1.0, "buyer_pride", "buyerPride", "buyer_pride_score"),
                dark_tolerance=_number(item, 5.0, "dark_tolerance", "darkTolerance"),
                self_ownable=_text(item, "self_ownable", "selfOwnable", "self_ownable_note"),
            )
        )
    return groups


def _read_slang(path: Path) -> list[SlangTerm]:
    rows = _rows(path, "terms", "slang", "lexicon", "items")
    terms = []
    for item in rows:
        term = _text(item, "term", "word", "slang", "name")
        if not term:
            continue
        terms.append(
            SlangTerm(
                term=term,
                meaning=_text(item, "meaning", "definition", "gloss"),
                register=_text(item, "register", "generation", "voice"),
                mismatch_score=_number(item, 0.0, "mismatch_score", "mismatch", "mismatchScore"),
            )
        )
    return terms


def _read_combos(path: Path) -> list[OverlapCombo]:
    rows = _rows(path, "combos", "overlaps", "pairs", "items")
    combos = []
    for item in rows:
        names = _texts(item, "names", "subgroups", "identities", "combo", "groups")
        if len(names) < 2:
            first = _text(item, "niche_a", "a", "name")
            second = _text(item, "niche_b", "b")
            third = _text(item, "niche_c", "c")
            names = [part for part in (first, second, third) if part]
        if len(names) < 2:
            continue
        combos.append(
            OverlapCombo(
                names=names[:3],
                shared_detail=_text(item, "shared_detail", "detail", "shared"),
                slang_hook=_text(item, "slang_hook", "hook", "slang"),
                buyer_pride=_number(item, 0.0, "buyer_pride", "buyerPride", "buyer_pride_score"),
            )
        )
    return combos


def _rows(path: Path, *wrappers: str) -> list[dict]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in wrappers:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _text(item: dict, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def _texts(item: dict, *keys: str) -> list[str]:
    for key in keys:
        value = item.get(key)
        if isinstance(value, list):
            return [" ".join(str(part).split()) for part in value if str(part).strip()]
        if isinstance(value, str) and value.strip():
            return [part.strip() for part in re.split(r"[,;|]", value) if part.strip()]
    nested = item.get("self_vs_outsider") or item.get("selfVsOutsider")
    if isinstance(nested, dict) and keys[0] in {"self_words", "outsider_words"}:
        side = "self" if keys[0] == "self_words" else "outsider"
        return _texts(nested, side, f"{side}_words")
    return []


def _number(item: dict, default: float, *keys: str) -> float:
    for key in keys:
        value = item.get(key)
        if isinstance(value, bool) or value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _average_pride(atlas: IdentityAtlas, names: list[str]) -> float:
    found = [atlas.lookup(name) for name in names]
    scores = [item.buyer_pride for item in found if item is not None]
    return sum(scores) / len(scores) if scores else 1.0


def _weighted_sample(
    weighted: list[tuple[float, dict]],
    limit: int,
    rng: random.Random,
) -> list[tuple[float, dict]]:
    pool = list(weighted)
    chosen: list[tuple[float, dict]] = []
    while pool and len(chosen) < limit:
        total = sum(weight for weight, _ in pool)
        ticket = rng.random() * total
        upto = 0.0
        index = 0
        for index, (weight, _) in enumerate(pool):
            upto += weight
            if upto >= ticket:
                break
        chosen.append(pool.pop(index))
    return chosen
