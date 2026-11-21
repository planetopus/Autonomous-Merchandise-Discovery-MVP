"""Humor tone, quote handoff, and the critic that cuts a large line batch."""

from pydantic import BaseModel, ConfigDict, Field

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
        "Identity stacks must name a real group whose traits genuinely co-occur, never a "
        "random combo. A generational or register mismatch is a key comedy lever: use words "
        "or habits the group would not use about themselves, and keep the line wholesome "
        "enough that a member thinks 'that's me' and would buy the sticker. "
        "Set truth to the one universal identity truth this line uses. "
        "Set comic_turn to ironic, sarcastic, or straight. Irony and sarcasm are core "
        "mechanics: reward a clear turn, not a straight description of a rule. "
        "Across the batch use at least 6 different pattern values and at least 4 different "
        "truths. Set who_its_for to 2 to 4 plain buyer categories, identity groups and "
        "interests, such as neighbors, commuters, and weeknight cooks. "
        "A line that only describes the behavior, with no ironic twist, fails. "
        "Set comic_turn to straight only when there is no turn. "
        "An absurd_identity_stack line is ALL CAPS and at most 6 words. "
        "A long literal duty list is not a stack. Shape only, do not output this line: "
        "THICC DADS WHO VAPE FOR CHRIST. "
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


def broad_identity_brief(query: str = "") -> str:
    """Keep an identity batch on universal truths instead of one narrow policy."""

    seasoning = ""
    cleaned = query.strip()
    if cleaned:
        seasoning = (
            f"The user mentioned {cleaned}. Treat that as optional seasoning for one line, "
            "not as the subject of the batch. "
        )
    return (
        "Choose the broad identity first, then 5 to 10 universal truths that almost everyone "
        "in it would recognize instantly: recurring objects, times, duties, and private jokes. "
        "Spread the lines across those truths. Set each candidate's truth field to the truth "
        "that line uses. "
        f"{seasoning}"
        "Source evidence may season a line. One narrow research thread, policy, ban, or "
        "confiscation rule must not define the whole batch. Do not write several versions of "
        "the same incident. Return topic_explored as the broad identity life, not a policy heading."
    )


def identity_stack_is_too_long(text: str, pattern: str) -> bool:
    """Club names are ALL CAPS and at most six words. A duty list is not a stack."""

    normalized = " ".join(pattern.casefold().replace("_", " ").replace("-", " ").split())
    if normalized != "absurd identity stack":
        return False
    words = [word for word in text.split() if any(character.isalpha() for character in word)]
    if len(words) > 6:
        return True
    letters = [character for character in text if character.isalpha()]
    return bool(letters) and not all(character.isupper() for character in letters)


def joke_key(text: str) -> str:
    """Collapse a line so near-duplicate jokes can be rejected."""

    return " ".join(text.casefold().split())


class HumorExampleRecord(BaseModel):
    """One reference line recorded on the run. Every field is required by strict mode."""

    model_config = ConfigDict(extra="forbid")

    text: str = ""
    upvotes: int = 0
    humor_type: str = ""
    niche: str = ""
    subreddit: str = ""
    post_url: str = ""


class LineReviewRecord(BaseModel):
    """One kept or dropped merchandise line from the critic."""

    model_config = ConfigDict(extra="forbid")

    artwork_text: str = ""
    pattern: str = ""
    who_its_for: list[str] = Field(default_factory=list, max_length=4)
    funny_score: float | None = None
    kept: bool = False
    reason: str = ""


class NichePairRecord(BaseModel):
    """One scored niche pair, including pairs the run did not keep."""

    model_config = ConfigDict(extra="forbid")

    niche_a: str = ""
    niche_b: str = ""
    shared_life_score: int = 0
    recognizability_score: int = 0
    reason: str = ""
    kept: bool = False


class PlaybookPatternRecord(BaseModel):
    """A playbook shape shown on the run page."""

    model_config = ConfigDict(extra="forbid")

    id: str = ""
    label: str = ""
    weight: int | None = None


class HumorCritiqueItem(BaseModel):
    """Critic scores for one drafted merchandise line."""

    model_config = ConfigDict(extra="forbid")

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
    instantly_understandable: float = Field(
        default=8,
        ge=1,
        le=10,
        description="Can a stranger understand the line in under 2 seconds?",
    )


class HumorCritiqueBatch(BaseModel):
    """Separate critic pass over one batch of drafted lines."""

    model_config = ConfigDict(extra="forbid")

    reviews: list[HumorCritiqueItem] = Field(min_length=1, max_length=30)


class NichePairCandidate(BaseModel):
    """One proposed niche collision and the two scores that decide whether it stays."""

    model_config = ConfigDict(extra="forbid")

    niche_a: str = Field(min_length=2, max_length=80)
    niche_b: str = Field(min_length=2, max_length=80)
    shared_life_score: int = Field(ge=1, le=10)
    recognizability_score: int = Field(ge=1, le=10)
    reason: str = Field(default="", max_length=300)


class NichePairBatch(BaseModel):
    """About ten niche pairs, each scored before any sticker line is written."""

    model_config = ConfigDict(extra="forbid")

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
        instantly_understandable: float | None = None,
    ):
        self.index = index
        self.humor_landed = humor_landed
        self.novelty = novelty
        self.tone_match = tone_match
        self.giftability = giftability
        self.reddit_upvote_score = reddit_upvote_score
        self.sticker_buy_score = sticker_buy_score
        self.instantly_understandable = instantly_understandable


def critic_average(review) -> float | None:
    """Weighted score. The member-buy test is half; Reddit and originality share the rest."""

    reddit = getattr(review, "reddit_upvote_score", None)
    sticker = getattr(review, "sticker_buy_score", None)
    originality = getattr(review, "novelty", None)
    if sticker is None:
        if reddit is None or originality is None:
            return None
        return (float(reddit) + float(originality)) / 2
    reddit_part = float(reddit) if reddit is not None else float(sticker)
    novelty_part = float(originality) if originality is not None else float(sticker)
    return (0.5 * float(sticker)) + (0.25 * novelty_part) + (0.25 * reddit_part)


def member_would_not_buy(review) -> bool:
    """The buy-it test outweighs a generic Reddit score.

    A line a real member would not buy is dropped even if Reddit would upvote it.
    A line a member would buy is not dropped just because the Reddit score is low.
    """

    if review is None:
        return False
    clear = getattr(review, "instantly_understandable", None)
    if clear is not None and float(clear) < 7:
        return True
    sticker = getattr(review, "sticker_buy_score", None)
    reddit = getattr(review, "reddit_upvote_score", None)
    if sticker is not None:
        return float(sticker) < 7
    return reddit is not None and float(reddit) < 7


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


def niche_pair_request(identity: str = "", bank: list[dict] | None = None) -> str:
    """Ask for about ten collisions and a score for each, before any joke is written."""

    named = identity.strip()
    anchor = (
        f'One side can be "{named}". The other side must be a different niche.\n'
        if named
        else ""
    )
    bank_lines = ""
    if bank:
        rendered = "\n".join(
            f'- {item["niche_a"]} + {item["niche_b"]}'
            for item in bank
            if item.get("niche_a") and item.get("niche_b")
        )
        if rendered:
            bank_lines = (
                "Score pairs from this bank first. Use one when its audiences really "
                "co-occur. Add a new pair only when none of these fit, and only if the "
                "traits genuinely co-occur.\n"
                f"{rendered}\n"
            )
    return (
        "Propose about 10 niche pairs for die-cut stickers. "
        "A good pair is two audiences that genuinely share a life, recognizable in one line. "
        "The traits must co-occur in a real group. Never propose a random combo. "
        "Do not prefer dads, nurses, or morticians. Cover identities that have not been used. "
        "Score each pair from 1 to 10 on shared_life_score (one person really lives both) "
        "and recognizability_score (a stranger gets the collision immediately). "
        "Do not propose a pair you would score under 7 on either axis.\n"
        f"{bank_lines}"
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
        turn = str(getattr(candidate, "comic_turn", "") or "").casefold()
        if turn in {"ironic", "sarcastic", "sarcasm"}:
            score += 3
        if member_would_not_buy(review):
            continue
        if str(getattr(candidate, "comic_turn", "") or "").casefold() == "straight":
            continue
        if identity_stack_is_too_long(
            str(getattr(candidate, "artwork_text", "") or ""),
            str(getattr(candidate, "pattern", "") or ""),
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
