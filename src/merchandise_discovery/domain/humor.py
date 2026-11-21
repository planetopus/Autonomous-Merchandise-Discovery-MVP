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
        "source you searched. That quote is evidence only. artwork_text must be an original "
        "joke, never the source sentence, a close paraphrase, or a title pun. "
        "Write in the insider voice of someone who lives the niche, about 4 to 14 words. "
        "Dark humor is welcome. "
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
            "No comments were prefetched. Use the search results and copy one verbatim sentence "
            "into source_quote as evidence. Do not use that sentence as artwork_text.\n"
        )
    lines = ["Use only these real comments. Do not invent a quote."]
    for index, quote in enumerate(quotes, start=1):
        body = " ".join(str(getattr(quote, "body", "")).split())
        url = getattr(quote, "url", "")
        score = getattr(quote, "score", 0)
        lines.append(f"{index}. (score {score}) {body} — {url}")
    lines.append(
        "Each candidate's source_quote must copy one of these comments verbatim as evidence. "
        "The merchandise line must be a new joke about that friction, not the comment itself."
    )
    return "\n".join(lines) + "\n"


def niche_pair_block(niche_a: str = "", niche_b: str = "", identity: str = "") -> str:
    """Require every run to cross two niches that share a real life."""

    first = niche_a.strip()
    second = niche_b.strip()
    named = identity.strip()
    shared = (
        "Return niche_pair_a, niche_pair_b, pairing_score from 0 to 10, and pairing_reason. "
        "pairing_score is how genuinely one person lives both and a stranger still gets the "
        "collision. Reject a pair you would score under 7 and choose another. "
        "Every merchandise line must carry both lives. Do not write a line that fits only one.\n"
    )
    if first and second:
        return (
            f'Cross these two niches exactly: "{first}" and "{second}". '
            "They must share a life, not sit side by side as unrelated subjects. "
            + shared
        )
    if named:
        return (
            f'The user named "{named}" as one side. Choose a second niche whose audience '
            "genuinely shares a life with that one: a job and a hobby, an identity and a life "
            "situation, or two communities. Do not stop at a single niche. "
            + shared
        )
    return (
        "The user did not name two niches. Before writing jokes, choose two different niches "
        "whose audiences genuinely share one life experience: a job and a hobby, an identity "
        "and a life situation, or two communities. Do not pick a single niche or a single topic. "
        + shared
    )


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
    sticker_buy_score: float = Field(
        default=8,
        ge=1,
        le=10,
        description="Would someone buy this exact line on a die-cut sticker.",
    )


class HumorCritiqueBatch(BaseModel):
    """Separate critic pass over one batch of drafted lines."""

    reviews: list[HumorCritiqueItem] = Field(min_length=1, max_length=30)


class NichePairCandidate(BaseModel):
    """One proposed niche collision and the two scores that decide whether it stays."""

    niche_a: str = Field(min_length=2, max_length=80)
    niche_b: str = Field(min_length=2, max_length=80)
    shared_life_score: int = Field(ge=1, le=10)
    recognizability_score: int = Field(ge=1, le=10)
    reason: str = Field(default="", max_length=300)


class NichePairBatch(BaseModel):
    """About ten niche pairs, each scored before any sticker line is written."""

    pairs: list[NichePairCandidate] = Field(min_length=1, max_length=12)


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
        sticker_buy_score: float | None = None,
    ):
        self.index = index
        self.humor_landed = humor_landed
        self.novelty = novelty
        self.tone_match = tone_match
        self.giftability = giftability
        self.reddit_upvote_score = reddit_upvote_score
        self.sticker_buy_score = sticker_buy_score


def critic_average(review) -> float | None:
    """Average of Reddit-upvote, sticker-buy, and originality. Missing scores do not invent one."""

    reddit = getattr(review, "reddit_upvote_score", None)
    sticker = getattr(review, "sticker_buy_score", None)
    originality = getattr(review, "novelty", None)
    if reddit is None or sticker is None or originality is None:
        return None
    return (float(reddit) + float(sticker) + float(originality)) / 3


def keep_strong_pairs(pairs: list) -> list:
    """Keep pairs that score at least 7 on both shared life and instant recognition."""

    strong = [
        pair
        for pair in pairs
        if pair.shared_life_score >= 7
        and pair.recognizability_score >= 7
        and pair.niche_a.strip().casefold() != pair.niche_b.strip().casefold()
    ]
    strong.sort(
        key=lambda pair: (
            -(pair.shared_life_score + pair.recognizability_score),
            pair.niche_a.casefold(),
        )
    )
    return strong


def niche_pair_request(identity: str = "") -> str:
    """Ask for about ten collisions and a score for each, before any joke is written."""

    named = identity.strip()
    anchor = (
        f'One side can be "{named}". The other side must be a different niche.\n'
        if named
        else ""
    )
    return (
        "Propose about 10 niche pairs for die-cut stickers. "
        "A good pair is two audiences that genuinely share a life, recognizable in one line. "
        "Examples of good pairs: nurses + true crime, dads + grilling. "
        "Score each pair from 1 to 10 on shared_life_score (one person really lives both) "
        "and recognizability_score (a stranger gets the collision immediately). "
        "Do not propose a pair you would score under 7 on either axis.\n"
        f"{anchor}"
    )


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
        average = critic_average(review) if review is not None else None
        if average is not None and average < 7:
            continue
        if (
            review is not None
            and average is None
            and review.reddit_upvote_score is not None
            and review.reddit_upvote_score < 7
        ):
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
