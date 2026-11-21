"""Select live humor references and reject sticker lines that copy them.

A separate sync writes the Mongo collection. This module only ranks what was loaded
and turns it into prompt text. It does not cache rows across runs.
"""

import hashlib
import math
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from merchandise_discovery.domain.models.common import HumorTone


class HumorReference(BaseModel):
    """One upvoted sticker line or theme stored for the copywriter."""

    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=1)
    upvotes: int = 0
    humor_type: str = ""
    niche: str = ""
    subreddit: str = ""
    post_url: str = ""
    date_found: str = ""
    is_theme: bool = False
    reference_id: str = ""


def normalize_reference_text(text: str) -> str:
    """Collapse a line so the same joke hashes and compares the same way."""

    return " ".join(text.casefold().split())


def humor_reference_id(text: str) -> str:
    """Stable Mongo `_id`: SHA-256 of the normalized sticker text."""

    return hashlib.sha256(normalize_reference_text(text).encode("utf-8")).hexdigest()


def text_is_theme(text: str, flagged: bool = False) -> bool:
    """Themes are explicit flags or rows whose text is marked `(theme)`."""

    return flagged or "(theme)" in text.casefold()


_TONE_TYPES = {
    HumorTone.WARM: {"niche-relatable"},
    HumorTone.DRY: {"dry"},
    HumorTone.SELF_DEPRECATING: {"niche-relatable", "dry"},
    HumorTone.DARK: {"dark", "unhinged"},
    HumorTone.EDGY: {"edgy", "absurd"},
}


@dataclass(frozen=True)
class HumorReferenceSelection:
    """Exact-text examples for the prompt, plus themes listed separately."""

    examples: list[HumorReference]
    themes: list[HumorReference]

    @property
    def display_examples(self) -> list[HumorReference]:
        """The ten highest-weighted examples to show on the run detail page."""

        return self.examples[:10]


def select_humor_references(
    references: list[HumorReference],
    *,
    tone: HumorTone | str | None,
    niches: list[str] | None = None,
    example_count: int = 32,
) -> HumorReferenceSelection:
    """Rank exact lines by log-scaled upvotes, with tone and niche boosts.

    Themes are excluded from the example list. `example_count` stays inside 25–40.
    """

    from merchandise_discovery.domain.humor import coerce_tone

    selected_tone = coerce_tone(tone)
    wanted = _TONE_TYPES[selected_tone]
    niche_terms = [term.casefold().strip() for term in (niches or []) if term and term.strip()]
    limit = min(40, max(25, example_count))
    themes = [item for item in references if item.is_theme]
    examples = [item for item in references if not item.is_theme]
    ranked = sorted(
        examples,
        key=lambda item: (
            -_reference_weight(item, wanted, niche_terms),
            -item.upvotes,
            item.text.casefold(),
        ),
    )
    themes_ranked = sorted(themes, key=lambda item: (-item.upvotes, item.text.casefold()))
    return HumorReferenceSelection(examples=ranked[:limit], themes=themes_ranked)


def _reference_weight(
    reference: HumorReference,
    wanted_types: set[str],
    niche_terms: list[str],
) -> float:
    """Log-scale upvotes, then boost a tone match or a niche overlap."""

    weight = math.log1p(max(reference.upvotes, 0))
    types = {part.strip().casefold() for part in reference.humor_type.split("/") if part.strip()}
    if types & wanted_types:
        weight *= 1.75
    if _niche_overlaps(reference.niche, niche_terms):
        weight *= 1.5
    return weight


def _niche_overlaps(reference_niche: str, niche_terms: list[str]) -> bool:
    """True when the reference niche and a run niche share a word or a phrase."""

    haystack = reference_niche.casefold()
    if not haystack or not niche_terms:
        return False
    haystack_tokens = set(re.findall(r"[a-z0-9]+", haystack))
    for term in niche_terms:
        if term in haystack or haystack in term:
            return True
        term_tokens = set(re.findall(r"[a-z0-9]+", term))
        if term_tokens and term_tokens & haystack_tokens:
            return True
    return False


def humor_reference_prompt(selection: HumorReferenceSelection) -> str:
    """Tell the writer to learn the joke mechanics without copying the examples."""

    if not selection.examples and not selection.themes:
        return ""
    lines = [
        (
            "Examples of what real people upvoted as funny. Learn the mechanics "
            "(specificity, misdirection, deadpan escalation, self-own, absurd literalism). "
            "Never copy or paraphrase them. A title or a pun alone is not a joke."
        ),
        (
            "Write a joke-shaped line: a setup plus a turn, a one-line confession, or a "
            "deadpan absurd statement, about 4 to 14 words."
        ),
    ]
    if selection.examples:
        lines.append("Exact-text examples, most upvoted first. Do not reuse this wording:")
        for item in selection.examples:
            label = item.humor_type or "unspecified"
            lines.append(f"- ({item.upvotes} upvotes, {label}) {item.text}")
    if selection.themes:
        lines.append("Currently funny topics, for subject matter only, not for wording:")
        for item in selection.themes:
            lines.append(f"- {item.text}")
    return "\n".join(lines) + "\n"


_SOURCE_STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "is",
    "it",
    "this",
    "that",
    "i",
    "my",
    "was",
    "were",
    "be",
    "at",
}


def copied_from_source(line: str, *sources: str) -> bool:
    """Reject a merchandise line that is mostly the source quote or excerpt."""

    line_norm = _comparison_text(line)
    if not line_norm:
        return False
    line_tokens = [token for token in line_norm.split() if token not in _SOURCE_STOPWORDS]
    for source in sources:
        source_norm = _comparison_text(source)
        if not source_norm:
            continue
        if line_norm == source_norm or (len(line_norm) >= 12 and line_norm in source_norm):
            return True
        if len(line_tokens) < 4:
            continue
        source_tokens = {token for token in source_norm.split() if token not in _SOURCE_STOPWORDS}
        if not source_tokens:
            continue
        overlap = len(set(line_tokens) & source_tokens) / len(line_tokens)
        if overlap >= 0.75:
            return True
    return False


def is_too_similar_to_references(candidate: str, references: list[HumorReference]) -> bool:
    """Reject a line that copies or lightly rewords an exact-text reference."""

    candidate_norm = _comparison_text(candidate)
    if not candidate_norm:
        return False
    candidate_tokens = set(candidate_norm.split())
    for reference in references:
        if reference.is_theme:
            continue
        reference_norm = _comparison_text(reference.text)
        if not reference_norm:
            continue
        if candidate_norm == reference_norm:
            return True
        if len(reference_norm) >= 12 and (
            reference_norm in candidate_norm or candidate_norm in reference_norm
        ):
            return True
        reference_tokens = set(reference_norm.split())
        if not candidate_tokens or not reference_tokens:
            continue
        overlap = len(candidate_tokens & reference_tokens) / len(candidate_tokens | reference_tokens)
        if overlap >= 0.72:
            return True
    return False


def _comparison_text(text: str) -> str:
    """Lowercase a line and drop punctuation before similarity checks."""

    lowered = text.casefold().replace("(theme)", " ")
    return " ".join(re.findall(r"[a-z0-9']+", lowered))
