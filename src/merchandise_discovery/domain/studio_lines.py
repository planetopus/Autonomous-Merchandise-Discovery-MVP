"""Studio sticker lines: wide draft, three gates, one style each.

Half the draft is a niche-crossover pun where the words and the picture are one joke.
Half is an original line in a shape taken from a proven top seller. Nothing in the
example list is a line to ship. Survivors keep a buyer label, a one-sentence scene,
and an art style that is not reused unless the run asked for flat vector only.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from merchandise_discovery.domain.humor import dark_humor_needed, is_dark_humor, spoof_earns_final
from merchandise_discovery.domain.humor_references import (
    HumorReference,
    copied_from_source,
    is_too_similar_to_references,
)

DRAFT_PER_HALF = 20
GATE_BATCH = 20

# Shapes the writer may learn from. The lines themselves are blocked as copies.
PROTECTED_EXAMPLES: tuple[str, ...] = (
    "Perennials Respawn. Annuals Rage Quit.",
    "Professional Purl Clutcher",
    "Indoor Recess: Final Boss",
    "Teacher HP 3%",
    "Most Wanted by Every Dog on My Route",
    "Last Call for Juice Boxes",
    "Fridge Opened 47 Times Today. No New Food Detected.",
    "PLEASE BE PATIENT: Driver Is Attempting the High Note",
    "Childbirth ★☆☆☆☆ Would Not Recommend (Did It 3 Times)",
    "My Bookmark Is Whatever Was Closest",
    "Here Lies Dad. He Knew a Shortcut.",
    "Knit Happens",
    "My TBR Is Load-Bearing",
    "Yes, I Can Back It In",
)

_CLICHE_PHRASES = (
    "knit happens",
    "live laugh love",
    "world's okayest",
    "worlds okayest",
    "keep calm and",
    "professional overthinker",
)

# Ten styles for a batch of ten. Flat vector stays available as the only style.
ART_STYLES: tuple[tuple[str, str], ...] = (
    (
        "flat vector",
        "Flat vector illustration: bold clean outlines, flat colors, no shading, no texture.",
    ),
    (
        "retro 70s badge",
        "Retro 1970s circular badge: warm sunset colors, thick rounded lettering, halftone dots.",
    ),
    (
        "hand-drawn marker",
        "Hand-drawn marker on white: uneven ink lines, a few bright marker colors, sketchy.",
    ),
    (
        "pixel art",
        "Pixel art: chunky pixels, a limited 8-bit palette, no smooth vectors.",
    ),
    (
        "vintage letterpress",
        "Vintage letterpress: worn metal type, slightly misregistered ink, cream and black.",
    ),
    (
        "risograph",
        "Risograph print: two or three overlapping ink colors, visible grain, misregistration.",
    ),
    (
        "fake warning label",
        "Fake warning label: hazard yellow and black, a simple icon, official-looking type.",
    ),
    (
        "distressed screen-print",
        "Distressed screen-print: one or two ink colors, cracked ink, slightly off-register.",
    ),
    (
        "ink-and-wash",
        "Ink and wash: black brush ink with one pale wash color, lots of white paper.",
    ),
    (
        "tattoo flash",
        "Traditional tattoo flash: heavy black line, a few solid colors, a simple banner.",
    ),
)


class StudioLine(BaseModel):
    """One drafted sticker before the gates."""

    model_config = ConfigDict(extra="forbid")

    artwork_text: str = Field(default="", max_length=160)
    buyer_groups: list[str] = Field(default_factory=list, max_length=4)
    scene: str = Field(default="", max_length=280)
    dark: bool = False
    spoof_brand: str = Field(default="", max_length=80)
    kind: str = Field(default="crossover", max_length=20)
    format_source: str = Field(default="", max_length=80)
    pattern: str = Field(default="", max_length=80)


class StudioBatch(BaseModel):
    """Up to twenty lines from one half of the draft."""

    model_config = ConfigDict(extra="forbid")

    lines: list[StudioLine] = Field(default_factory=list, max_length=24)


class ComedyGateItem(BaseModel):
    """Harsh comedy-critic score for one drafted line."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    passed: bool = False
    score: float = Field(default=0, ge=0, le=10)
    reason: str = ""
    cliche: bool = False
    instant: bool = False
    one_joke: bool = False
    brand_fits: bool = True
    brand_joke_link: str = ""


class ComedyGateBatch(BaseModel):
    """One critic call. Batches stay at twenty so the call stays short."""

    model_config = ConfigDict(extra="forbid")

    reviews: list[ComedyGateItem] = Field(default_factory=list, max_length=24)


class BuyerGateItem(BaseModel):
    """Whether the named buyer group would pay for this exact sticker."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    would_buy: bool = False
    reason: str = ""


class BuyerGateBatch(BaseModel):
    """One buyer-in-the-niche call for a batch of drafted lines."""

    model_config = ConfigDict(extra="forbid")

    reviews: list[BuyerGateItem] = Field(default_factory=list, max_length=24)


@dataclass
class ScoredLine:
    """A draft plus the two review gates. The sale check is applied after this."""

    text: str
    buyers: list[str]
    scene: str
    dark: bool
    spoof_brand: str
    kind: str
    format_source: str
    pattern: str
    score: float
    brand_fits: bool
    brand_joke_link: str
    critic_ok: bool
    buyer_ok: bool
    critic_reason: str
    buyer_reason: str
    for_sale_url: str = ""

    def probe(self):
        """A small object the existing spoof and dark-humor checks already understand."""

        return _Probe(
            artwork_text=self.text,
            pattern="dark twist scene" if self.dark else self.pattern,
            spoof_brand=self.spoof_brand,
            brand_fits=self.brand_fits,
            brand_joke_link=self.brand_joke_link,
            funny_score=self.score,
            humor_mechanism="gallows" if self.dark else self.kind,
            image_idea=self.scene,
            why_it_works=self.scene,
        )


class _Probe:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def is_cliche(text: str) -> bool:
    """Local backstop for lines the critic is told to reject on sight."""

    lowered = " ".join(text.casefold().split())
    return any(phrase in lowered for phrase in _CLICHE_PHRASES)


def comedy_passed(review: ComedyGateItem | None, text: str) -> bool:
    """A line clears the critic only when every strict flag agrees."""

    if review is None or is_cliche(text):
        return False
    if review.cliche or not review.instant or not review.one_joke or not review.passed:
        return False
    try:
        score = float(review.score)
    except (TypeError, ValueError):
        return False
    return score >= 7


def line_counts_as_dark(line: ScoredLine) -> bool:
    """Writer-marked dark humor, or a line the shared dark-humor check already recognizes."""

    return bool(line.dark) or is_dark_humor(line.probe())


def protected_references() -> list[HumorReference]:
    """The method examples are style, not lines that can ship."""

    return [
        HumorReference(text=text, upvotes=1, humor_type="example") for text in PROTECTED_EXAMPLES
    ]


def reject_unoriginal(
    lines: list[ScoredLine],
    references: list | None = None,
) -> tuple[list[ScoredLine], list[ScoredLine]]:
    """Drop a line that copies an example, a gold line, or a top-seller reference."""

    library = [*protected_references(), *(references or [])]
    extra = list(PROTECTED_EXAMPLES)
    kept: list[ScoredLine] = []
    dropped: list[ScoredLine] = []
    seen: set[str] = set()
    for line in lines:
        key = " ".join(line.text.casefold().split())
        copied = (
            not key
            or key in seen
            or is_cliche(line.text)
            or copied_from_source(line.text, *extra)
            or is_too_similar_to_references(line.text, library)
        )
        if copied:
            dropped.append(line)
            continue
        seen.add(key)
        kept.append(line)
    return kept, dropped


def select_studio_finals(
    lines: list[ScoredLine],
    keep_count: int,
    *,
    flat_only: bool,
) -> tuple[list[tuple[ScoredLine, str, str]], str]:
    """Keep the best lines, with one dark joke when the batch is large enough.

    Brand spoofs stay only when the existing bar says the brand is why it is funny.
    Art styles do not repeat. Flat-only runs use the flat vector style on every line.
    """

    eligible = [
        line
        for line in lines
        if line.critic_ok
        and line.buyer_ok
        and not line.for_sale_url
        and spoof_earns_final(line.probe())
    ]
    ranked = sorted(eligible, key=lambda line: (-line.score, line.text.casefold()))
    limit = max(1, keep_count)
    if not flat_only:
        limit = min(limit, len(ART_STYLES))
    chosen: list[ScoredLine] = []
    seen: set[str] = set()
    need_dark = dark_humor_needed(limit, 0)
    if need_dark:
        for line in ranked:
            if line_counts_as_dark(line):
                chosen.append(line)
                seen.add(line.text.casefold())
                break
    for line in ranked:
        if len(chosen) >= limit:
            break
        key = line.text.casefold()
        if key in seen:
            continue
        chosen.append(line)
        seen.add(key)
    note = ""
    if keep_count > limit and not flat_only:
        note = "Kept one sticker per art style."
    if limit >= 5 and not any(line_counts_as_dark(line) for line in chosen):
        extra = "No dark-humor line cleared the gates."
        note = f"{note} {extra}".strip()
    return _with_styles(chosen, flat_only=flat_only), note


def _with_styles(
    lines: list[ScoredLine],
    *,
    flat_only: bool,
) -> list[tuple[ScoredLine, str, str]]:
    flat_name, flat_note = ART_STYLES[0]
    if flat_only:
        return [(line, flat_name, flat_note) for line in lines]
    ranked = sorted(lines, key=lambda line: (-line.score, line.text.casefold()))
    style_for = {line.text: ART_STYLES[index] for index, line in enumerate(ranked)}
    return [(line, *style_for[line.text]) for line in lines]


def studio_image_prompt(text: str, scene: str, style_name: str, style_note: str) -> str:
    """Build the image prompt from the exact line, the scene, and one style."""

    cleaned = " ".join(text.split())
    picture = " ".join(scene.split()) or "One subject whose picture completes the joke."
    if cleaned:
        lettering = (
            f'Text appears exactly once, spelled exactly: "{cleaned}". '
            "Do not add any other words and do not repeat the line."
        )
    else:
        lettering = "Merchandise text: none. Do not render any words."
    prompt = (
        "Die-cut vinyl sticker on a plain white background. "
        "One isolated subject, thick white outline, no mockup, no poster, no extra caption. "
        f"Art style: {style_name}. {style_note} "
        f"Scene, and the picture carries the joke: {picture} "
        f"{lettering}"
    )
    if len(prompt) < 180:
        prompt += " Keep the sticker centered with empty white around the die-cut shape."
    return prompt


def crossover_writer_prompt(
    *,
    groups: list[dict],
    tone: str,
    quotes: str = "",
) -> str:
    """Ask for niche-crossover puns. The examples are shapes, not lines to copy."""

    group_lines = [
        f"- {item.get('niche_a', '')} + {item.get('niche_b', '')}"
        for item in groups
        if item.get("niche_a") and item.get("niche_b")
    ]
    group_block = (
        "\n".join(group_lines) or "- gardeners + gamers\n- knitters + their own hobby panic"
    )
    banned = "; ".join(f'"{line}"' for line in PROTECTED_EXAMPLES[:8])
    return (
        f"Write {DRAFT_PER_HALF} original die-cut sticker lines. "
        "Each one is a niche crossover built on a pun. The words and the picture make ONE joke. "
        f"Tone: {tone}.\n"
        "Rotate across these buyer pairs. Set buyer_groups to that pair's two labels. "
        "Set kind to crossover. Set scene to one sentence where the picture carries the joke. "
        "At least two lines are dark humor with dark true. "
        "Set spoof_brand only when that brand is the joke, otherwise leave it empty. "
        "Do not swap a brand name in just to look clever.\n"
        "Shapes to learn from, and then NOT copy:\n"
        '- Gardeners who game: a plant-care word used as a game rule, as in "Perennials Respawn. '
        'Annuals Rage Quit."\n'
        '- Knitters: a stitch name that is also a panic, as in "Professional Purl Clutcher".\n'
        '- Teachers who game: recess or grading as a boss fight, as in "Indoor Recess: Final Boss" '
        'or "Teacher HP 3%".\n'
        "- Mail carriers: the route as a wanted poster, as in "
        '"Most Wanted by Every Dog on My Route".\n'
        '- Parents who also tend bar: bedtime as last call, as in "Last Call for Juice Boxes".\n'
        f"Never write these lines or a close paraphrase: {banned}. "
        "Reject clichés such as Knit Happens.\n"
        f"Buyer pairs:\n{group_block}\n"
        f"{quotes}"
    )


def format_writer_prompt(
    *,
    market_block: str,
    tone: str,
    quotes: str = "",
) -> str:
    """Ask for original lines in proven top-seller shapes. Do not copy the examples."""

    signal = market_block.strip() or (
        "No top-seller list was loaded. Invent the buyer yourself from a specific real group."
    )
    banned = "; ".join(f'"{line}"' for line in PROTECTED_EXAMPLES[6:])
    return (
        f"Write {DRAFT_PER_HALF} ORIGINAL die-cut sticker lines. "
        "Each one reverse-engineers a proven top-selling format. Steal the shape, write a new joke. "
        f"Tone: {tone}. Set kind to format. Set format_source to the shape name, not a product title. "
        "Set buyer_groups to 2 to 4 labels for the exact people who would buy it. "
        "Set scene to one sentence where the picture carries the joke. "
        "At least two lines are dark humor with dark true. "
        "A brand spoof is allowed only when that brand is why the joke is funny.\n"
        "Shapes, with an example that must NOT be copied:\n"
        "- Ring-doorbell meme: a device reports a disappointing count. "
        'Example of the shape only: "Fridge Opened 47 Times Today. No New Food Detected."\n'
        "- Student-driver magnet: PLEASE BE PATIENT, then the person is attempting one hard "
        'specific thing. Example: "PLEASE BE PATIENT: Driver Is Attempting the High Note".\n'
        "- One-star review: the experience, one filled star, Would Not Recommend, and a count. "
        'Example: "Childbirth ★☆☆☆☆ Would Not Recommend (Did It 3 Times)".\n'
        "- Book sticker: a reading habit stated as a physical fact. "
        'Example: "My Bookmark Is Whatever Was Closest".\n'
        "- Tombstone decal, dark humor allowed: Here Lies, a role, and a deadpan specific. "
        'Example: "Here Lies Dad. He Knew a Shortcut."\n'
        f"Never write these lines or a close paraphrase: {banned}.\n"
        "Use this top-seller signal for WHO is buying and which subjects are selling. "
        "Do not copy product wording.\n"
        f"{signal}\n"
        f"{quotes}"
    )


def comedy_gate_prompt(lines: list[ScoredLine]) -> str:
    """Number a batch for the harsh critic. Indexes are 0-based."""

    rows = []
    for index, line in enumerate(lines):
        brand = f" Brand spoof of {line.spoof_brand}." if line.spoof_brand else ""
        rows.append(
            f'{index}. "{line.text}" Picture: {line.scene or "unspecified"}.{brand} '
            f"Buyers: {', '.join(line.buyers) or 'unspecified'}."
        )
    return (
        "Score every index once. passed is true only at 7 or higher when the line is instant, "
        "not a cliché, and the words plus the picture are one joke. "
        "For a brand spoof, brand_fits is true only when that brand is why it is funny, "
        "and brand_joke_link is that one sentence.\n" + "\n".join(rows)
    )


def buyer_gate_prompt(lines: list[ScoredLine]) -> str:
    """Number a batch for the buyer who would actually wear it."""

    rows = []
    for index, line in enumerate(lines):
        buyers = ", ".join(line.buyers) or "the named group"
        rows.append(
            f'{index}. Buyers: {buyers}. Line: "{line.text}" Picture: {line.scene or "unspecified"}.'
        )
    return (
        "For each index, would_buy is true only if that exact group would laugh and buy the sticker. "
        "A clever line they would not wear is false.\n" + "\n".join(rows)
    )


COMEDY_GATE_SYSTEM = (
    "You are a harsh comedy critic who has already seen every sticker cliché. "
    "Reject 'Knit Happens', 'Live Laugh Love', 'World's Okayest', 'Keep Calm', "
    "title puns, lines that do not make sense in one second, and forced brand-name swaps. "
    "A brand spoof passes only when the brand's product or slogan is the joke. "
    "The words and the picture must be ONE joke. If the line is just as funny with no picture, "
    "or the picture only illustrates the words, set one_joke false and passed false. "
    "Set instant false when a stranger would need the line explained. "
    "Set cliche true for a stock slogan. score is 1 to 10. passed requires score >= 7."
)

BUYER_GATE_SYSTEM = (
    "You are a real member of the buyer group named on each line, and you have five dollars "
    "for one sticker. would_buy is true only if you would laugh and put it on your water bottle "
    "or give it to someone in that exact group. Clever is not enough. If you would not buy it, "
    "would_buy is false and reason says why in one sentence."
)


def scored_from_draft(draft: StudioLine) -> ScoredLine | None:
    """Turn one model line into a scored row. Empty text is dropped."""

    text = " ".join(draft.artwork_text.split())
    if len(text) < 2:
        return None
    buyers = []
    for label in draft.buyer_groups:
        cleaned = " ".join(str(label).split())
        if cleaned and cleaned.casefold() not in {item.casefold() for item in buyers}:
            buyers.append(cleaned[:40])
        if len(buyers) == 4:
            break
    pattern = draft.pattern.strip() or (
        "wordplay pun" if draft.kind != "format" else "slogan twist"
    )
    if draft.dark:
        pattern = "dark twist scene"
    if draft.spoof_brand.strip():
        pattern = "brand logo spoof"
    return ScoredLine(
        text=text[:160],
        buyers=buyers,
        scene=" ".join(draft.scene.split())[:280],
        dark=bool(draft.dark),
        spoof_brand=draft.spoof_brand.strip()[:80],
        kind=draft.kind.strip() or "crossover",
        format_source=draft.format_source.strip()[:80],
        pattern=pattern[:80],
        score=0,
        brand_fits=True,
        brand_joke_link="",
        critic_ok=False,
        buyer_ok=False,
        critic_reason="",
        buyer_reason="",
    )


def apply_gate_reviews(
    lines: list[ScoredLine],
    comedy: list[ComedyGateItem],
    buyers: list[BuyerGateItem],
) -> list[ScoredLine]:
    """Stamp critic and buyer results onto one batch. A missing review fails that gate."""

    comedy_by_index = {item.index: item for item in comedy}
    buyer_by_index = {item.index: item for item in buyers}
    stamped: list[ScoredLine] = []
    for index, line in enumerate(lines):
        review = comedy_by_index.get(index)
        buyer = buyer_by_index.get(index)
        line.critic_ok = comedy_passed(review, line.text)
        line.critic_reason = "" if review is None else " ".join(review.reason.split())[:300]
        if review is not None:
            line.score = float(review.score)
            line.brand_fits = bool(review.brand_fits)
            line.brand_joke_link = " ".join(review.brand_joke_link.split())[:240]
            if review.cliche or is_cliche(line.text):
                line.critic_reason = line.critic_reason or "cliché"
        else:
            line.critic_reason = "no critic review"
        line.buyer_ok = buyer is not None and bool(buyer.would_buy)
        line.buyer_reason = "" if buyer is None else " ".join(buyer.reason.split())[:300]
        if buyer is None:
            line.buyer_reason = "no buyer review"
        stamped.append(line)
    return stamped


def apply_sale_flags(lines: list[ScoredLine], hits: dict[str, str]) -> list[ScoredLine]:
    """Mark lines whose exact phrase is already for sale. The URL is the evidence."""

    for line in lines:
        line.for_sale_url = hits.get(line.text, "")
    return lines


def chunked(lines: list[ScoredLine], size: int = GATE_BATCH) -> list[list[ScoredLine]]:
    """Split a draft into critic-sized batches."""

    step = max(1, size)
    return [lines[index : index + step] for index in range(0, len(lines), step)]
