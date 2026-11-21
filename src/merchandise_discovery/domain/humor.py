"""Humor tone, quote handoff, and the critic that cuts a large line batch."""

from pydantic import BaseModel, Field

from merchandise_discovery.domain.models.common import HumorTone


def coerce_tone(tone: HumorTone | str | None) -> HumorTone:
    """Accept the enum or the stored string and fall back to dry."""

    if isinstance(tone, HumorTone):
        return tone
    try:
        return HumorTone(str(tone or HumorTone.DRY.value))
    except ValueError:
        return HumorTone.DRY


def humor_prompt_suffix(tone: HumorTone | str | None) -> str:
    """Return the copy rules shared by every merchandise-line prompt."""

    selected = coerce_tone(tone)
    rules = (
        f"Requested humor tone: {selected.value} ({selected.description}). "
        "Every candidate must name humor_mechanism, the device that makes the joke work "
        "(recognition, reversal, understatement, exaggeration, or gallows), and "
        "concrete_detail, one object, time, or action taken from the source. "
        "Set source_quote to a verbatim sentence from a supplied comment or from the "
        "source you searched. The merchandise line must point at that quote. "
    )
    if selected == HumorTone.DARK:
        return (
            rules
            + "Dark mode allows gallows and bleak humor. Do not invent sensitive traits, "
            "diagnoses, trauma, or private facts about real people. Do not soften a landed "
            "dark joke to make it more giftable."
        )
    if selected == HumorTone.EDGY:
        return (
            rules
            + "Edgy humor can be sharp, but it still cannot invent sensitive traits, "
            "diagnoses, or private facts about real people."
        )
    return (
        rules
        + "Stay inside the requested tone. Do not invent sensitive traits about real people."
    )


def quote_block(quotes: list | None) -> str:
    """Tell the writer which real comments to point at, or to quote a searched source."""

    if not quotes:
        return (
            "No comments were prefetched. Use the search results, copy one verbatim sentence "
            "into source_quote, and point the merchandise line at that sentence.\n"
        )
    lines = ["Use only these real comments. Do not invent a quote."]
    for index, quote in enumerate(quotes, start=1):
        body = " ".join(str(getattr(quote, "body", "")).split())
        url = getattr(quote, "url", "")
        score = getattr(quote, "score", 0)
        lines.append(f"{index}. (score {score}) {body} — {url}")
    lines.append(
        "Each candidate's source_quote must copy one of these comments verbatim, and the "
        "line must point at the friction in that comment."
    )
    return "\n".join(lines) + "\n"


def joke_key(text: str) -> str:
    """Collapse a line so near-duplicate jokes can be rejected."""

    return " ".join(text.casefold().split())


class HumorCritiqueItem(BaseModel):
    """Critic scores for one drafted merchandise line."""

    index: int = Field(ge=0)
    humor_landed: float = Field(ge=0, le=10)
    novelty: float = Field(ge=0, le=10)
    tone_match: float = Field(ge=0, le=10)
    giftability: float = Field(default=5, ge=0, le=10)
    reddit_upvote_score: float = Field(
        default=8,
        ge=1,
        le=10,
        description="Would this line get upvoted on Reddit, judged against the reference jokes.",
    )


class HumorCritiqueBatch(BaseModel):
    """Separate critic pass over a batch of drafted lines."""

    reviews: list[HumorCritiqueItem] = Field(min_length=1, max_length=25)


class LineReview:
    """One critic score row. A simple object keeps the critic independent of provider models."""

    def __init__(
        self,
        index: int,
        humor_landed: float,
        novelty: float,
        tone_match: float,
        giftability: float = 5.0,
        reddit_upvote_score: float | None = None,
    ):
        self.index = index
        self.humor_landed = humor_landed
        self.novelty = novelty
        self.tone_match = tone_match
        self.giftability = giftability
        self.reddit_upvote_score = reddit_upvote_score


def apply_line_critic(candidates: list, reviews: list, *, keep_count: int, tone: HumorTone | str) -> list:
    """Keep the lines where the joke landed and cut the rest.

    Giftability is ignored when the run asked for dark humor, so a bleak line is not
    removed for being a poor gift.
    """

    selected = coerce_tone(tone)
    by_index = {review.index: review for review in reviews}
    ranked: list[tuple[float, float, int, object]] = []
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        review = by_index.get(index)
        humor = review.humor_landed if review is not None else 5.0
        novelty = review.novelty if review is not None else 5.0
        tone_match = review.tone_match if review is not None else 5.0
        giftability = review.giftability if review is not None else 5.0
        if selected == HumorTone.DARK:
            score = humor + novelty + tone_match
        else:
            score = humor + novelty + tone_match + (0.25 * giftability)
        if review is not None and review.reddit_upvote_score is not None and review.reddit_upvote_score < 7:
            continue
        key = joke_key(str(getattr(candidate, "artwork_text", "") or getattr(candidate, "phrase", "")))
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        ranked.append((score, humor, index, candidate))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    strong = [item for item in ranked if item[1] >= 5]
    pool = strong if len(strong) >= min(keep_count, len(ranked)) and strong else ranked
    kept = [item[3] for item in pool[:keep_count]]
    return kept or [ranked[0][3]] if ranked else []
