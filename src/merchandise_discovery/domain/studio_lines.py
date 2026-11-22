"""Studio sticker lines: a real moment, one twist, then the gates.

Each line starts from an everyday moment a real group already recognizes, then
adds exactly one pun or twist. Stacked puns and invented splices never score.
Nothing in the example list is a line to ship. Survivors keep real buyer labels,
a one-sentence scene, and an art style that is not reused unless the run asked
for flat vector only.
"""

import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from merchandise_discovery.domain.humor import dark_humor_needed, is_dark_humor, spoof_earns_final
from merchandise_discovery.domain.humor_references import (
    HumorReference,
    copied_from_source,
    is_too_similar_to_references,
)

DRAFT_PER_HALF = 10
GATE_BATCH = 20
REFILL_CAP = 2

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
    "I Rolled a Natural 1 on Bedtime.",
    "Awarded One Star. By the Smoke Alarm.",
    "Leave Only Footprints. Take Only Ibuprofen.",
    "My Starter Left Me on Read.",
    "I Grounded the Panel. I Cannot Ground My Teen.",
    "OSHA Would Like a Word With My Weekend.",
    "Sorry I Missed Your Call. I Saw It Happen.",
    "We Started Leaving Yesterday.",
    "Most Likely To Bring a Side and a Grudge.",
    "Text Me When You Get There. I'll Be Watching the Dots.",
    "I Tabbed the Red Flags. Then I Married Him.",
)

_PLACEHOLDER_BUYERS = {
    "this group",
    "people who know them",
    "people who recognize it",
    "unspecified",
    "the named group",
    "buyers",
    "everyone",
    "people",
    "a group",
    "the group",
}

_CONTRACTIONS = {
    "i'm",
    "i'd",
    "i'll",
    "i've",
    "don't",
    "doesn't",
    "didn't",
    "can't",
    "won't",
    "isn't",
    "aren't",
    "wasn't",
    "weren't",
    "haven't",
    "hasn't",
    "hadn't",
    "wouldn't",
    "couldn't",
    "shouldn't",
    "it's",
    "that's",
    "there's",
    "here's",
    "what's",
    "who's",
    "let's",
    "you're",
    "we're",
    "they're",
    "you've",
    "we've",
    "they've",
    "you'd",
    "we'd",
    "they'd",
    "you'll",
    "we'll",
    "they'll",
    "y'all",
    "ya'll",
    "ma'am",
    "o'clock",
    "ain't",
}

# A third one of these in a short line is a second joke piled on the first.
_STACKED_TOKENS = {
    "boss",
    "unlock",
    "unlocks",
    "unlocked",
    "level",
    "levels",
    "respawn",
    "respawns",
    "loot",
    "quest",
    "quests",
    "npc",
    "xp",
    "hp",
    "raid",
    "raids",
    "spawn",
    "spawns",
}

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
    stacked: bool = False
    invented_mashup: bool = False
    would_buy: bool = False
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


def real_buyers(labels: list[str] | None) -> list[str]:
    """Buyer names a person would recognize. Placeholders such as 'this group' are dropped."""

    kept: list[str] = []
    seen: set[str] = set()
    for label in labels or []:
        cleaned = " ".join(str(label).split())
        key = cleaned.casefold()
        if not cleaned or key in _PLACEHOLDER_BUYERS or key in seen:
            continue
        seen.add(key)
        kept.append(cleaned[:40])
        if len(kept) == 4:
            break
    return kept


def invented_splice(text: str) -> bool:
    """A made-up apostrophe splice, such as Ope'n. Ordinary contractions stay."""

    for token in re.findall(r"[A-Za-z]+'[A-Za-z]+", text or ""):
        if token.casefold() not in _CONTRACTIONS:
            return True
    return False


def stacked_pun(text: str) -> bool:
    """Two punchlines joined, or three game-words piled onto one line."""

    if ";" in (text or ""):
        return True
    tokens = set(re.findall(r"[a-z0-9']+", (text or "").casefold()))
    return len(tokens & _STACKED_TOKENS) >= 3


def sticker_too_long(text: str) -> bool:
    """A sticker slogan is about 4 to 14 words. A run-on does not fit."""

    words = re.findall(r"[A-Za-z0-9']+", text or "")
    return len(words) > 16


def local_sense_failure(line: ScoredLine) -> str:
    """The hard gate before any score. Empty means the line may be judged."""

    if invented_splice(line.text):
        return "invented mashup"
    if stacked_pun(line.text):
        return "stacked puns"
    if sticker_too_long(line.text):
        return "too long for a sticker"
    if not real_buyers(line.buyers):
        return "no real buyer group"
    return ""


def comedy_passed(review: ComedyGateItem | None, text: str) -> bool:
    """Clarity first. A clever line that is stacked, spliced, or slow does not pass."""

    if review is None or is_cliche(text) or invented_splice(text) or stacked_pun(text):
        return False
    if (
        review.cliche
        or review.stacked
        or review.invented_mashup
        or not review.instant
        or not review.one_joke
        or not review.passed
    ):
        return False
    try:
        score = float(review.score)
    except (TypeError, ValueError):
        return False
    return score >= 7


def dark_punchline_survives(review: ComedyGateItem | None, line: ScoredLine) -> bool:
    """A clear dark joke is not dropped for being dark."""

    if review is None or not line_counts_as_dark(line):
        return False
    if (
        review.cliche
        or review.stacked
        or review.invented_mashup
        or not review.instant
        or not review.one_joke
    ):
        return False
    try:
        return float(review.score) >= 7
    except (TypeError, ValueError):
        return False


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
        and not local_sense_failure(line)
        and spoof_earns_final(line.probe())
    ]
    for line in eligible:
        line.buyers = real_buyers(line.buyers)
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


# Three illustrations of the move. Not a menu of slogans to fill in.
MOVE_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("parents at bedtime", "I Rolled a Natural 1 on Bedtime."),
    ("a cook and a smoke alarm", "Awarded One Star. By the Smoke Alarm."),
    ("a baker whose starter stalled", "My Starter Left Me on Read."),
    ("people who started leaving early", "We Started Leaving Yesterday."),
    ("an introvert who saw the call", "Sorry I Missed Your Call. I Saw It Happen."),
)


def template_key(text: str) -> str:
    """The protected opening, if this line is a fill-in of one slogan."""

    lowered = " ".join(str(text or "").casefold().split())
    if lowered.startswith("here lies"):
        return "here lies"
    if lowered.startswith("please be patient"):
        return "please be patient"
    if "★" in str(text or "") or "would not recommend" in lowered:
        return "star rating"
    return ""


def limit_template_openings(
    lines: list[ScoredLine],
) -> tuple[list[ScoredLine], list[ScoredLine]]:
    """Keep the first line of each protected opening and drop the repeats."""

    seen: set[str] = set()
    kept: list[ScoredLine] = []
    dropped: list[ScoredLine] = []
    for line in lines:
        key = template_key(line.text)
        if key and key in seen:
            line.critic_ok = False
            line.buyer_ok = False
            line.critic_reason = f"repeated {key} template"
            dropped.append(line)
            continue
        if key:
            seen.add(key)
        kept.append(line)
    return kept, dropped


def calibration_block() -> str:
    """Two or three examples of the move: a real moment, then one twist."""

    rows = [
        f'- The moment stays off the sticker. The line is the punchline: "{line}" ({who})'
        for who, line in MOVE_EXAMPLES
    ]
    return (
        "Ship the punchline, not a description of the moment. Do not output these lines.\n"
        + "\n".join(rows)
        + "\nA line that only narrates the scene is wrong. One opening per batch.\n"
    )


def _avoid_block(avoid: list[str]) -> str:
    """Every earlier line, with nothing cut off for length."""

    lines = [text.strip() for text in avoid if text and str(text).strip()]
    if not lines:
        return "Do not repeat an earlier line.\n"
    body = "\n".join(f'- "{text}"' for text in lines)
    return f"Do not repeat any of these lines:\n{body}\n"


def _subject_hint(market_block: str) -> str:
    """Top sellers name subjects. They do not name the buyer."""

    text = market_block.strip()
    if not text:
        return ""
    return (
        "Subject hint only. These topics are selling. They do not change who the line is for.\n"
        f"{text}\n"
    )


def _audience_rule(groups: list[dict]) -> str:
    """Every draft is for the chosen person, not a rotation of other buyers."""

    if len(groups) == 1:
        first = str(groups[0].get("niche_a") or "").strip()
        second = str(groups[0].get("niche_b") or "").strip()
        return (
            f'Every line is for one person who is "{first}" and "{second}". '
            f'buyer_groups must include "{first}" and "{second}". '
            "Do not write for a different group.\n"
        )
    return (
        "Every line is for one person named below. buyer_groups names that person. "
        "Do not invent a different audience.\n"
        f"{_group_block(groups)}\n"
    )


def studio_target_groups(supplied: list[str], bank: list[dict] | None = None) -> list[dict]:
    """One pair, unless the run named more than two identities on purpose."""

    names = [" ".join(name.split()) for name in supplied if name and str(name).strip()]
    catalog = bank or []
    if len(names) == 2:
        return [{"niche_a": names[0], "niche_b": names[1]}]
    if len(names) > 2:
        return [{"niche_a": names[0], "niche_b": name} for name in names[1:]]
    if len(names) == 1:
        wanted = names[0].casefold()
        for item in catalog:
            sides = (
                str(item.get("niche_a") or "").strip(),
                str(item.get("niche_b") or "").strip(),
            )
            folded = (sides[0].casefold(), sides[1].casefold())
            if wanted not in folded:
                continue
            other = sides[1] if folded[0] == wanted else sides[0]
            return [{"niche_a": names[0], "niche_b": other or "everyday life"}]
        partner = str(catalog[0].get("niche_b") or "").strip() if catalog else ""
        return [{"niche_a": names[0], "niche_b": partner or "everyday life"}]
    for item in catalog:
        first = str(item.get("niche_a") or "").strip()
        second = str(item.get("niche_b") or "").strip()
        if first and second:
            return [{"niche_a": first, "niche_b": second}]
    return [{"niche_a": "parents", "niche_b": "everyday life"}]


def _group_block(groups: list[dict]) -> str:
    lines = [
        f"- {item.get('niche_a', '')} + {item.get('niche_b', '')}"
        for item in groups
        if item.get("niche_a") and item.get("niche_b")
    ]
    return "\n".join(lines) or "- parents + a hobby one parent actually has"


def _moment_rules(count: int, tone: str) -> str:
    return (
        f"Write {count} sticker slogans. Tone: {tone}.\n"
        "Each slogan is a real moment this person knows, plus ONE punchline. "
        "The moment is the setup. artwork_text is only the punchline, 4 to 14 words, "
        "the kind of line a stranger laughs at in 2 seconds.\n"
        "Wrong: 'Stirring the soup, I scratch one between stirs.' That only describes the scene.\n"
        "Right: a short slogan with one turn, such as a game word on bedtime or a texting "
        "phrase on a stalled starter. Do not copy the examples.\n"
        "One pun only. A second pun, a stacked game phrase, or a made-up splice "
        "such as Ope'n is a failed line. A run-on is a failed line.\n"
        "buyer_groups is the chosen person's real labels. Never write 'this group'. "
        "scene is one sentence where the picture carries that punchline. "
        "At least one line is dark humor with a real punchline, dark true. "
        "A dark punchline is still a joke, not a description of a funeral. "
        "spoof_brand stays empty unless that brand is the punchline.\n"
    )


def crossover_writer_prompt(
    *,
    groups: list[dict],
    tone: str,
    quotes: str = "",
    batch_label: str = "MOMENT CROSSOVER",
    count: int | None = None,
) -> str:
    """Ask for one real overlap and one twist. The examples are not lines to copy."""

    total = count or DRAFT_PER_HALF
    return (
        f"{batch_label}.\n"
        f"{_moment_rules(total, tone)}"
        f"{_audience_rule(groups)}"
        "Set kind to crossover. The two labels are one person, not two jokes.\n"
        f"{calibration_block()}"
        f"{quotes}"
    )


def format_writer_prompt(
    *,
    market_block: str,
    tone: str,
    groups: list[dict] | None = None,
    quotes: str = "",
    batch_label: str = "PROVEN FORMAT",
    shapes: str = "all",
    count: int | None = None,
) -> str:
    """Ask for one line per shape, for the same person as the other drafts."""

    if shapes == "count":
        total = 2
        shape_block = (
            "Write exactly 2 lines, one per shape. Do not write a second line in either shape.\n"
            "- One disappointing count: a habit or device reports a number, and the number is the letdown.\n"
            "- One patience sign: ask the reader to wait while this person attempts one hard thing.\n"
        )
    elif shapes == "plaque":
        total = 3
        shape_block = (
            "Write exactly 3 lines, one per shape. Do not write a second line in any shape.\n"
            "- One object gives a one-star verdict on a real mishap.\n"
            "- One reading habit stated as a single physical fact.\n"
            "- One tombstone: this person's role and one deadpan fact. Set dark true.\n"
        )
    else:
        total = count or 5
        shape_block = (
            "Write one line per shape, and no seconds.\n"
            "- One disappointing count.\n"
            "- One patience sign for one hard attempt.\n"
            "- One one-star verdict from one object.\n"
            "- One reading habit as a physical fact.\n"
            "- One tombstone with one deadpan fact. Set dark true.\n"
        )
    return (
        f"{batch_label}.\n"
        f"{_moment_rules(total, tone)}"
        f"{_audience_rule(groups or [])}"
        "Set kind to format. Set format_source to the shape, not a product title. "
        "Each shape is used once. Do not stack two shapes in one line.\n"
        f"{shape_block}"
        f"{calibration_block()}"
        f"{_subject_hint(market_block)}"
        f"{quotes}"
    )


def studio_opening_prompts(
    *,
    groups: list[dict],
    market_block: str,
    tone: str,
    quotes: str = "",
) -> list[str]:
    """Four short drafts in parallel, instead of two long ones."""

    pair = groups[:1] or [{"niche_a": "parents", "niche_b": "everyday life"}]
    return [
        crossover_writer_prompt(
            groups=pair,
            tone=tone,
            quotes=quotes,
            count=8,
            batch_label="MOMENT CROSSOVER A",
        ),
        crossover_writer_prompt(
            groups=pair,
            tone=tone,
            count=8,
            batch_label="MOMENT CROSSOVER B",
        ),
        format_writer_prompt(
            market_block=market_block,
            tone=tone,
            groups=pair,
            batch_label="PROVEN FORMAT A",
            shapes="count",
        ),
        format_writer_prompt(
            market_block=market_block,
            tone=tone,
            groups=pair,
            batch_label="PROVEN FORMAT B",
            shapes="plaque",
        ),
    ]


def refill_writer_prompt(
    *,
    count: int,
    avoid: list[str],
    groups: list[dict],
    tone: str,
    market_block: str,
) -> str:
    """One short extra batch for the lines still missing. It does not redo the whole draft."""

    return (
        "REFILL.\n"
        f"{_moment_rules(count, tone)}"
        f"{_audience_rule(groups)}"
        "Set kind to crossover or format. Each format shape at most once.\n"
        f"{_avoid_block(avoid)}"
        f"{calibration_block()}"
        f"{_subject_hint(market_block)}"
    )


def dark_refill_prompt(*, groups: list[dict], tone: str) -> str:
    """One short call when a batch of ten has no dark line."""

    return (
        "DARK REFILL.\n"
        f"{_moment_rules(2, tone)}"
        f"{_audience_rule(groups)}"
        "Both lines are dark humor this person would tell about their own life. "
        "Set dark true. One twist only.\n"
        f"{calibration_block()}"
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
        "Require a punchline. A line that only describes a scene fails, even if the scene is specific. "
        "instant means a stranger laughs in 2 seconds. one_joke means exactly one pun or twist. "
        "A run-on or a caption scores 4 or under and passed is false. "
        "Dark humor with a punchline passes. Do not fail it for being dark. "
        "'Saving a seat at the service. Winner must be present.' is a clear dark joke. "
        "would_buy is true when that group would laugh and pay, including at a dark joke. "
        "passed requires instant, one_joke, not stacked, not a mashup, and clarity >= 7.\n"
        + "\n".join(rows)
    )


COMEDY_GATE_SYSTEM = (
    "You judge sticker slogans. A line that only describes a scene fails, even if it is specific. "
    "instant is false when a stranger would not laugh in 2 seconds. "
    "one_joke is false when there is no punchline, or when two puns are stacked. "
    "invented_mashup is true for a made-up splice such as Ope'n. "
    "A run-on scores 4 or under. "
    "Dark humor is allowed. Do not fail instant, one_joke, or would_buy because the joke is "
    "about death, a funeral, or gallows humor. "
    "'Saving a seat at the service. Winner must be present.' passes. "
    "would_buy is true when that group would laugh and buy it, including a dark punchline. "
    "passed is true only when there is one clear punchline and clarity is at least 7. "
    "Reject Knit Happens, Live Laugh Love, World's Okayest, and Keep Calm."
)

STUDIO_WRITER_SYSTEM = (
    "You write short sticker slogans. Each one is a punchline, not a description of a scene. "
    "A real moment is the setup. The words on the sticker are the one twist that makes a stranger laugh. "
    "4 to 14 words. Never copy an example. Never stack a second pun. "
    "Never invent a splice such as Ope'n. "
    "Dark humor with a punchline is welcome. A scene caption is not. "
    "buyer_groups is the real labels, never 'this group'."
)


def scored_from_draft(draft: StudioLine) -> ScoredLine | None:
    """Turn one model line into a scored row. Empty text is dropped."""

    text = " ".join(draft.artwork_text.split())
    if len(text) < 2:
        return None
    buyers = real_buyers(list(draft.buyer_groups))
    pattern = draft.pattern.strip() or (
        "wordplay pun" if draft.kind != "format" else "slogan twist"
    )
    dark = bool(draft.dark) or template_key(text) == "here lies"
    if dark:
        pattern = "dark twist scene"
    if draft.spoof_brand.strip():
        pattern = "brand logo spoof"
    return ScoredLine(
        text=text[:160],
        buyers=buyers,
        scene=" ".join(draft.scene.split())[:280],
        dark=dark,
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
        failure = local_sense_failure(line)
        review = comedy_by_index.get(index)
        buyer = buyer_by_index.get(index)
        if failure:
            line.critic_ok = False
            line.buyer_ok = False
            line.score = 0
            line.critic_reason = failure
            line.buyer_reason = failure
            stamped.append(line)
            continue
        line.critic_ok = comedy_passed(review, line.text)
        line.critic_reason = "" if review is None else " ".join(review.reason.split())[:300]
        if review is not None:
            line.score = 0 if not line.critic_ok else float(review.score)
            line.brand_fits = bool(review.brand_fits)
            line.brand_joke_link = " ".join(review.brand_joke_link.split())[:240]
            if review.cliche or is_cliche(line.text):
                line.critic_reason = line.critic_reason or "cliché"
            if review.stacked or review.invented_mashup or not review.instant:
                line.critic_reason = line.critic_reason or "does not make sense in 2 seconds"
        else:
            line.critic_reason = "no critic review"
            line.score = 0
        would_buy = bool(review.would_buy) if review is not None else False
        if buyer is not None:
            would_buy = bool(buyer.would_buy)
            line.buyer_reason = " ".join(buyer.reason.split())[:300]
        elif review is not None:
            line.buyer_reason = line.critic_reason
        else:
            line.buyer_reason = "no buyer review"
        if dark_punchline_survives(review, line):
            line.critic_ok = True
            line.buyer_ok = True
            if review is not None and line.score < float(review.score):
                line.score = float(review.score)
            line.buyer_reason = line.buyer_reason or "dark punchline"
        else:
            line.buyer_ok = bool(line.critic_ok and would_buy)
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
