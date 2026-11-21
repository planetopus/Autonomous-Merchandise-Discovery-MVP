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
    "self_words": ("self_words", "selfWords", "insider_words", "words_they_use", "self_terms"),
    "outsider_words": ("outsider_words", "outsiderWords", "words_outsiders_use", "outsider_terms"),
    "overlaps": ("overlaps", "co_occurrences", "cooccurrences", "co_occurring", "overlaps_with"),
}
# Auto niche picks stay on identities a buyer is proud of, not a job crossed with a hobby.
BROAD_APPEAL_PARENTS = {
    "body & looks": "body",
    "life stages": "age",
    "generations": "age",
    "family roles": "family",
    "religion & church": "faith",
    "us regions": "region",
    "small town & rural": "region",
    "vices & habits": "vice",
    "personality & temperament": "personality",
}
_BROAD_DIMENSIONS = set(BROAD_APPEAL_PARENTS.values())
_ACRONYMS = {
    "it": "IT",
    "hr": "HR",
    "er": "ER",
    "icu": "ICU",
    "adhd": "ADHD",
    "ocd": "OCD",
    "rv": "RV",
    "dnd": "D&D",
    "usa": "USA",
}


@dataclass
class IdentitySubgroup:
    """One atlas subgroup, with only the fields the prompts actually use."""

    name: str
    subgroup_id: str = ""
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
        """Match a display name or a raw id, ignoring case and extra words."""

        key = name.casefold().strip()
        if not key:
            return None
        indexed = self._index().get(key)
        if indexed is not None:
            return indexed
        partial = [
            item
            for item in self.subgroups
            if item.name.casefold() in key or key in item.name.casefold()
        ]
        return partial[0] if partial else None

    def _index(self) -> dict[str, IdentitySubgroup]:
        cached = getattr(self, "_lookup_index", None)
        if cached is not None:
            return cached
        index: dict[str, IdentitySubgroup] = {}
        for item in self.subgroups:
            index.setdefault(item.name.casefold(), item)
            if item.subgroup_id:
                index.setdefault(item.subgroup_id.casefold(), item)
        self._lookup_index = index
        return index


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


def diversity_factor(names: list[str], recent_counts: dict[str, int]) -> float:
    """Downweight identities already used. Familiar groups get no extra boost."""

    factor = 1.0
    for token in _identity_tokens(names):
        factor *= 1.0 / (1 + recent_counts.get(token, 0))
    return factor


def buyer_groups_block(pairs: list[dict]) -> str:
    """Ask one text call to write across several buyer groups."""

    if len(pairs) < 3:
        return ""
    lines = [
        (
            "Write this batch across these different buyer groups. "
            "Do not make every line about the same person. "
            "Cover at least 3 of these groups. "
            "Set each line's who_its_for to that group's plain labels only."
        )
    ]
    for index, pair in enumerate(pairs[:5], start=1):
        lines.append(f"{index}. {pair.get('niche_a', '')} + {pair.get('niche_b', '')}")
    return "\n".join(lines) + "\n"


def sample_overlap_pairs(
    atlas: IdentityAtlas,
    *,
    anchor: str = "",
    limit: int = 10,
    rng: random.Random | None = None,
    avoid: list[str] | None = None,
    trend: dict[str, float] | None = None,
) -> list[dict]:
    """Sample real overlaps, weighted by buyer-pride and what is selling."""

    if not atlas.subgroups and not atlas.combos:
        return []
    chooser = rng or random.Random()
    weighted: list[tuple[float, dict]] = []
    seen: set[tuple[str, str]] = set()
    anchor_key = anchor.casefold().strip()

    def add(weight: float, names: list[str], detail: str = "", hook: str = "") -> None:
        raw = [name.strip() for name in names if name and name.strip()]
        if len(raw) < 2:
            return
        groups = [atlas.lookup(name) for name in raw]
        if any(is_narrow_identity(group) for group in groups):
            return
        cleaned = [
            group.name if group is not None else humanize_label(name)
            for name, group in zip(raw, groups, strict=True)
        ]
        if anchor_key and not any(
            anchor_key in name.casefold() or name.casefold() in anchor_key
            for name in cleaned + raw
        ):
            return
        key = tuple(sorted(name.casefold() for name in cleaned))
        if key in seen:
            return
        seen.add(key)
        weighted.append(
            (
                max(weight, 0.1) * _trend_factor(cleaned + raw, trend),
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
    counts = _token_counts(avoid or [])
    pool = list(weighted)
    chosen: list[dict] = []
    while pool and len(chosen) < limit:
        scored = [
            (
                pride * diversity_factor([item["niche_a"], item["niche_b"]], counts),
                item,
            )
            for pride, item in pool
        ]
        _, pick = _pick_weighted(scored, chooser)
        chosen.append(pick)
        pool = [(pride, item) for pride, item in pool if item is not pick]
        for token in _identity_tokens([pick["niche_a"], pick["niche_b"]]):
            counts[token] = counts.get(token, 0) + 1
    return chosen


def _trend_factor(names: list[str], trend: dict[str, float] | None) -> float:
    """Boost a pair whose identity tokens are in the selling signal. Unlisted pairs stay at 1."""

    if not trend:
        return 1.0
    factor = 1.0
    seen: set[str] = set()
    for token in _identity_tokens(names):
        boost = trend.get(token)
        if boost and token not in seen:
            seen.add(token)
            factor *= boost
    return min(factor, 4.0)


def appeal_of(group: IdentitySubgroup | None) -> str:
    """Return body, age, family, faith, region, vice, or personality when the group is one."""

    if group is None:
        return ""
    for raw in (group.parent, group.dimension):
        key = raw.casefold().strip()
        if key in BROAD_APPEAL_PARENTS:
            return BROAD_APPEAL_PARENTS[key]
        if key in _BROAD_DIMENSIONS:
            return key
    return ""


def is_narrow_identity(group: IdentitySubgroup | None) -> bool:
    """A known job, hobby, or fandom. Unknown fixtures are not treated as narrow."""

    if group is None or appeal_of(group):
        return False
    return bool((group.parent or group.dimension).strip())


def humanize_label(value: str) -> str:
    """Turn a raw id into words. Display names that already have spaces stay as written."""

    text = " ".join(str(value or "").split())
    if not text or " " in text or "_" not in text:
        return text
    words = []
    for part in text.split("_"):
        words.append(_ACRONYMS.get(part.casefold(), part.capitalize()))
    return " ".join(word for word in words if word)


def display_name(value: str, atlas: IdentityAtlas | None = None) -> str:
    """Use the atlas name for an id, otherwise readable words."""

    text = " ".join(str(value or "").split())
    if not text:
        return ""
    if atlas is not None:
        found = atlas.lookup(text)
        if found is not None and (
            text.casefold() == found.subgroup_id.casefold() or ("_" in text and " " not in text)
        ):
            return found.name
        if found is not None and text.casefold() == found.name.casefold():
            return found.name
    return humanize_label(text)


def infer_who_its_for(
    labels: list[str] | None,
    names: list[str],
    groups: list[IdentitySubgroup] | None = None,
    atlas: IdentityAtlas | None = None,
) -> list[str]:
    """Return 2 to 4 readable buyer categories for the line's real audience."""

    collected: list[str] = []
    chosen: set[str] = set()
    for name in names:
        for part in re.split(r"\s+\+\s+|,\s*", name):
            found = atlas.lookup(part) if atlas is not None else None
            if found is not None:
                chosen.add(found.name.casefold())
                if found.subgroup_id:
                    chosen.add(found.subgroup_id.casefold())
            elif part.strip():
                chosen.add(part.casefold())

    def add(value: object) -> None:
        text = display_name(str(value or ""), atlas)
        if not text or len(text) > 40 or "_" in text:
            return
        if text.casefold() in {item.casefold() for item in collected}:
            return
        collected.append(text)

    def extra_overlap(value: str) -> bool:
        if atlas is None:
            return "_" in value and " " not in value
        found = atlas.lookup(value)
        if found is None:
            return "_" in value and " " not in value
        key = value.casefold().strip()
        id_like = key == found.subgroup_id.casefold() or ("_" in value and " " not in value)
        if not id_like:
            return False
        return found.name.casefold() not in chosen and found.subgroup_id.casefold() not in chosen

    for label in labels or []:
        if extra_overlap(str(label)):
            continue
        add(label)
    for name in names:
        for part in re.split(r"\s+\+\s+|,\s*", name):
            add(part)
    for group in groups or []:
        add(group.name)
        if group.parent and appeal_of(group):
            add(group.parent)
    if len(collected) == 1:
        add("people who know them")
    if len(collected) < 2:
        add("this group")
        add("people who recognize it")
    return collected[:4]


def format_who_its_for(labels: list[str]) -> str:
    """Render buyer categories the way the run page and exports show them."""

    return " · ".join(labels[:4])


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
            bits.append("traits: " + "; ".join(group.traits[:3]))
        if group.self_words:
            bits.append("words they use: " + ", ".join(group.self_words[:4]))
        if group.outsider_words:
            bits.append("outsider words: " + ", ".join(group.outsider_words[:4]))
        bits.append(f"buyer-pride {group.buyer_pride:g}, dark tolerance {group.dark_tolerance:g}")
        if group.self_ownable:
            bits.append(f"self-ownable: {group.self_ownable}")
        lines.append("- " + ". ".join(bits))
    if slang:
        lines.append("High-mismatch slang. Use at most one, and only if it fits:")
        for term in slang[:4]:
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
                subgroup_id=_text(item, "id"),
                parent=_text(item, "parent", "group", "category", "parent_group"),
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
        names = _texts(item, "subgroup_names", "names", "identities")
        if len(names) < 2:
            names = _texts(item, "subgroups", "combo", "groups")
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
                shared_detail=_text(item, "shared_detail", "detail", "shared", "shared_truth"),
                slang_hook=_text(item, "slang_hook", "hook", "slang"),
                buyer_pride=_number(
                    item,
                    0.0,
                    "buyer_pride",
                    "buyerPride",
                    "buyer_pride_score",
                    "min_buyer_pride",
                ),
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


def _identity_tokens(names: list[str]) -> list[str]:
    tokens: list[str] = []
    for name in names:
        for token in re.findall(r"[a-z0-9]+", name.casefold()):
            if len(token) < 3 or token in {"the", "and", "who", "for", "with", "from"}:
                continue
            if token not in tokens:
                tokens.append(token)
    return tokens


def _token_counts(names: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in _identity_tokens(names):
        counts[token] = counts.get(token, 0) + 1
    return counts


def _pick_weighted(scored: list[tuple[float, dict]], rng: random.Random) -> tuple[float, dict]:
    total = sum(max(weight, 0.0) for weight, _ in scored) or 1.0
    ticket = rng.random() * total
    upto = 0.0
    for weight, item in scored:
        upto += max(weight, 0.0)
        if upto >= ticket:
            return weight, item
    return scored[-1]


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
