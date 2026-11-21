"""Humor tone, quote handoff, and the critic that cuts a large line batch."""

import re

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
        "joke, never the source sentence or a close paraphrase. "
        "Write in the insider voice of someone who lives the niche, about 4 to 14 words. "
        "A pun, spoof, or name swap is 2 to 8 words. "
        "At least 3 of every 5 final lines must be one of those. "
        "Dark humor is welcome. "
        "Identity stacks must name a real group whose traits genuinely co-occur, never a "
        "random combo. A generational or register mismatch is a key comedy lever: use words "
        "or habits the group would not use about themselves, and keep the line wholesome "
        "enough that a member thinks 'that's me' and would buy the sticker. "
        "Set truth to the one universal identity truth this line uses. "
        "Primary mode is sarcasm, irony, and wit. At least 70% of the lines must be "
        "sarcastic understatement, situational or dramatic irony, or a clever wordplay "
        "or reversal. Identity stacks are the secondary mode: still write at least two, "
        "and do not let them replace the jokes. "
        "About 30 to 40 percent of the lines must be puns or spoofs. "
        "Each concept is one word-and-image pair, not a line with a picture added later. "
        "The picture must complete, flip, or reveal the double meaning. "
        "Set image_idea to that picture in one sentence. "
        "Set why_it_works to one sentence on how the words and the picture combine. "
        "Set format to the layout, such as retro sunset badge, logo spoof, circle badge, "
        "bold text stack, bumper sticker strip, warning sign, plaque, or oval outdoor badge. "
        "Use wordplay_pun, image_pun, celebrity_food_pun, brand_logo_spoof, "
        "innocent_image_innuendo, cute_but_menacing, dark_twist_scene, catchphrase_flip, "
        "relatable_confession_action, pop_culture_quote_flip, historical_name_pun, "
        "fake_acronym_org, fake_warning_sign, slogan_twist, rhyme_innuendo, or holiday_pun. "
        "At least 2 of every 5 lines must be brand_logo_spoof: a major brand's logo "
        "layout and colors with new pun text for this buyer. Set spoof_brand to that brand. "
        "A spoof of a famous logo, celebrity, or movie character is allowed. "
        "Mild crude or adult innuendo is allowed when the picture completes the joke. "
        "The wholesome bar applies to identity stacks, not to these pairs. "
        "Text only in this step. Do not generate an image. "
        "Do not reprint an anchor line or a close swap of one. "
        "Set comic_turn to ironic, sarcastic, or straight. Irony and sarcasm are core "
        "mechanics: reward a clear turn, not a straight description of a rule. "
        "The turn may live in the picture. "
        "Across the batch use at least 6 different pattern values and at least 4 different "
        "truths. Set who_its_for to 2 to 4 plain buyer categories, identity groups and "
        "interests, such as neighbors, commuters, and weeknight cooks. "
        "A line that only describes the behavior, with no ironic twist, fails. "
        "Stack 2 or 3 true identity traits and one specific twist. "
        "A single famous trope is not a sticker. "
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


def pun_examples_block() -> str:
    """Best-seller word-and-image pairs. Learn the pairing. Do not reprint the lines."""

    return (
        "Pun and spoof pairs. The words and the picture are one joke. "
        "Learn the pairing. Do not reprint these lines.\n"
        "- celebrity_food_pun | bold text stack | TOAST MALONE | "
        "a slice of toast with Post Malone's face tattoos | "
        "the name is the celebrity until the toast shows the food pun.\n"
        "- brand_logo_spoof | logo spoof | THIS MIGHT BE VODKA | "
        "the Starbucks siren logo with that ring text | "
        "the logo says coffee and the words flip the cup.\n"
        "- brand_logo_spoof | logo spoof | BACK & BODY HURTS | "
        "a Bath & Body Works pink logo on blue gingham | "
        "the store logo makes the ache look like a product.\n"
        "- brand_logo_spoof | logo spoof | WHY DON'T YOU BLOW ME | "
        "a Bubble Yum style bubble-gum logo | "
        "the gum logo turns the demand into a brand spoof.\n"
        "- innocent_image_innuendo | bold text stack | SOMETIMES I WET MY PLANTS | "
        "potted succulents | the plants reveal the innocent meaning.\n"
        "- innocent_image_innuendo | bold text stack | SUC MY CAC | "
        "a cactus in a pot | the cactus makes the crude reading a plant pun.\n"
        "- innocent_image_innuendo | bold text stack | DON'T BE A CUNTASAURUS | "
        "a cute dinosaur | the cute dinosaur lets the insult stay a joke.\n"
        "- innocent_image_innuendo | retro sunset badge | JUST THE TIP | "
        "Michael Myers holding a knife, retro stripes | "
        "the knife completes the phrase the words leave hanging.\n"
        "- innocent_image_innuendo | retro sunset badge | SHOW ME YOUR KITTIES | "
        "a cool cat in sunglasses on a retro sunset | "
        "the cat takes the phrase away from the crude reading.\n"
        "- cute_but_menacing | circle badge | PEACE WAS NEVER AN OPTION | "
        "a cute duck holding a knife | the duck looks sweet and the knife flips it.\n"
        "- dark_twist_scene | retro sunset badge | "
        "BRING A COMPASS, IT'S AWKWARD WHEN YOU HAVE TO EAT YOUR FRIENDS | "
        "a hiker silhouette on a mountain with a bear | "
        "the pretty badge turns into the dark hike.\n"
        "- catchphrase_flip | circle badge | "
        "THICK THIGHS SAVE LIVES / BUT THIGH HIGHS ARE MY DEMISE | "
        "a torso in thigh-high stockings, warning-badge style | "
        "the second line and the stockings flip the slogan.\n"
        "- relatable_confession_action | bold text stack | "
        "I'M JUST HERE TO GET DRUNK AND DRIVE THE GOLF CART | "
        "a stick figure drinking in a golf cart chasing running golfers | "
        "the chase shows the confession instead of restating it.\n"
        "- wordplay_pun | bold text stack | I have patients, not patience | "
        "a waiting-room clock melting | the clock shows patience running out.\n"
        "- pop_culture_quote_flip | bold text stack | BOLDLY GOING NOWHERE... | "
        "the Star Trek phrase on a galaxy background | "
        "the voyage slogan stalls, and the galaxy shows the trip that never starts.\n"
        "- pop_culture_quote_flip | bold text stack | CAN WE FIX IT? NO. IT'S FUCKED. | "
        "Bob the Builder waving | the catchphrase answers itself and the wave sells the no.\n"
        "- pop_culture_quote_flip | retro sunset badge | ONLY YOU CAN PREVENT DRAMA | "
        "a llama in a ranger hat and sunglasses | "
        "the Smokey Bear pose makes the drama warning a PSA parody.\n"
        "- pop_culture_quote_flip | logo spoof | THIS IS A TASTY BEVERAGE | "
        "Samuel L. Jackson sipping, inside a Starbucks ring | "
        "the burger quote becomes a drink, and the ring makes it a cafe order.\n"
        "- brand_logo_spoof | logo spoof | BEST BUTT | "
        "the Best Buy yellow tag logo | the price tag turns the store name into the joke.\n"
        "- holiday_pun | bold text stack | THAT'S SOME BOO SHEET! | "
        "a cute trick-or-treat ghost with a pumpkin bucket | "
        "the ghost makes boo sheet a Halloween pun.\n"
        "- innocent_image_innuendo | bold text stack | SUCK MY BALLS | "
        "a cute kawaii boba tea with tapioca balls | "
        "the tapioca balls take the phrase off the crude reading.\n"
        "- innocent_image_innuendo | oval outdoor badge | LET'S GET WET | "
        "a kayaker on a mountain lake | the lake makes the phrase an outdoor boast.\n"
        "- historical_name_pun | bold text stack | BEN DRANKIN | "
        "Ben Franklin in a flag headband and aviators, holding a shot | "
        "the portrait turns the name into the drinking pun.\n"
        "- brand_logo_spoof | logo spoof | ALDEEZ NUTS | "
        "the Aldi logo layout | the store mark makes the snack pun look official.\n"
        "- fake_acronym_org | plaque | D.A.M.M. DRUNKS AGAINST MAD MOTHERS | "
        "a plain black plaque | the plaque parodies MADD and the letters spell the joke.\n"
        "- fake_warning_sign | warning sign | WARNING: DANGEROUS GASSES | "
        "a pictogram figure farting | the warning layout makes the pictogram the punchline.\n"
        "- innocent_image_innuendo | circle badge | MASTER BAITER - World Class | "
        "a fishing lure | the lure reveals the fishing title.\n"
        "- innocent_image_innuendo | bold text stack | SEND NOODS | "
        "a ramen bowl and chopsticks | the noodles take the phrase off the crude reading.\n"
        "- innocent_image_innuendo | bold text stack | NOT MY PASTURE, NOT MY BULLSHIT | "
        "a cow with a sunflower crown | the crowned cow makes the farm saying the joke.\n"
        "- slogan_twist | bumper sticker strip | FIGHT CRIME, SHOOT BACK | "
        "a pistol on a bumper-sticker strip | the strip flips a civic slogan.\n"
        "- rhyme_innuendo | bold text stack | "
        "DON'T FORGET THE VASOLINE WHEN YOU GET THE GASOLINE | "
        "a gas nozzle and a Vaseline jar drawn into the letters | "
        "the rhyme and the two icons are the same joke.\n"
        "Formats to reuse: retro sunset badge, logo spoof, circle badge, bold text stack, "
        "bumper sticker strip, warning sign, plaque, oval outdoor badge. "
        "Parody of a famous logo, celebrity, or movie character is allowed. "
        "Mild adult innuendo is allowed when the picture completes it. "
        "About 30 to 40 percent of the batch uses these shapes. "
        "Every concept sets image_idea, why_it_works, and format. "
        "Text only. Do not generate an image.\n"
    )


_ANCHOR_TEXTS = (
    "TOAST MALONE",
    "THIS MIGHT BE VODKA",
    "BACK & BODY HURTS",
    "WHY DON'T YOU BLOW ME",
    "SOMETIMES I WET MY PLANTS",
    "SUC MY CAC",
    "DON'T BE A CUNTASAURUS",
    "JUST THE TIP",
    "SHOW ME YOUR KITTIES",
    "PEACE WAS NEVER AN OPTION",
    "BRING A COMPASS, IT'S AWKWARD WHEN YOU HAVE TO EAT YOUR FRIENDS",
    "THICK THIGHS SAVE LIVES",
    "I'M JUST HERE TO GET DRUNK AND DRIVE THE GOLF CART",
    "I HAVE PATIENTS, NOT PATIENCE",
    "BOLDLY GOING NOWHERE",
    "CAN WE FIX IT? NO. IT'S FUCKED.",
    "BEN DRANKIN",
    "ALDEEZ NUTS",
    "D.A.M.M. DRUNKS AGAINST MAD MOTHERS",
    "WARNING: DANGEROUS GASSES",
    "MASTER BAITER",
    "SEND NOODS",
    "NOT MY PASTURE, NOT MY BULLSHIT",
    "FIGHT CRIME, SHOOT BACK",
    "DON'T FORGET THE VASOLINE WHEN YOU GET THE GASOLINE",
    "ONLY YOU CAN PREVENT DRAMA",
    "THIS IS A TASTY BEVERAGE",
    "BEST BUTT",
    "THAT'S SOME BOO SHEET",
    "SUCK MY BALLS",
    "LET'S GET WET",
    "NACHO AVERAGE NURSE",
    "I KNEAD COFFEE",
    "GRILL SERGEANT",
    "PICKLEBALL IS MY CARDIO",
    "GUAC IS EXTRA",
    "I DO STEP CLASS EVERY OTHER WEEKEND",
    "WINTER IS NOT COMING",
    "BE KIND, REWIND MY BACK",
    "I WAS GIFTED, NOW I'M RE-GIFTED",
    "CODE BREW",
)


def finished_sticker_examples_block() -> str:
    """The finished-sticker look. Short pun, character, layout. Do not reprint the lines."""

    return (
        "Finished sticker style. 2 to 8 words. A cute or iconic character makes the "
        "second meaning. At least 3 of 5 final lines are a pun, spoof, or name swap. "
        "Learn the pairing. Do not reprint these lines.\n"
        "- NACHO AVERAGE NURSE | tortilla chip in scrubs, cap, stethoscope, clipboard | "
        "bold text top and bottom\n"
        "- I KNEAD COFFEE | grumpy cat kneading a steaming mug | arched bold text\n"
        "- GRILL SERGEANT | burger in a drill hat and aviators with a spatula | "
        "circular retro sunset badge\n"
        "- PICKLEBALL IS MY CARDIO (AND MY GOSSIP) | pickle in a visor with a paddle | "
        "retro stripes\n"
        "- GUAC IS EXTRA / SO IS RENT | sad avocado in a cart with an overdue bill | "
        "bold text stack\n"
        "- I DO STEP CLASS EVERY OTHER WEEKEND | stepmom on a stair-stepper with kids' bags\n"
        "- WINTER IS NOT COMING | snowbird in a Hawaiian shirt, parka on the ground | "
        "retro sunset palm badge\n"
        "- BE KIND, REWIND MY BACK | VHS tape in a back brace | 90s rental ticket spoof\n"
        "- I WAS GIFTED, NOW I'M RE-GIFTED | tired gift box, droopy bow\n"
        "- CODE BREW | coffee mug on a crash cart | medical badge\n"
    )


def is_anchor_echo(text: str) -> bool:
    """True when a line repeats an anchor or a near-duplicate of one."""

    candidate = _anchor_norm(text)
    if not candidate:
        return False
    candidate_tokens = set(candidate.split())
    for anchor in _ANCHOR_TEXTS:
        source = _anchor_norm(anchor)
        if not source:
            continue
        if candidate == source:
            return True
        if len(source) >= 12 and (source in candidate or candidate in source):
            return True
        source_tokens = set(source.split())
        if not candidate_tokens or not source_tokens:
            continue
        overlap = len(candidate_tokens & source_tokens) / len(candidate_tokens | source_tokens)
        if overlap >= 0.72:
            return True
    return False


def is_brand_spoof(candidate) -> bool:
    """A major-brand logo layout with new pun text."""

    if pattern_key(candidate) == "brand logo spoof":
        return True
    return bool(str(getattr(candidate, "spoof_brand", "") or "").strip())


def _kept_score(candidate) -> float:
    value = getattr(candidate, "funny_score", None)
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def order_kept_lines(candidates: list, keep_count: int) -> list:
    """Highest scores first, after two brand spoofs and three puns are seated."""

    if keep_count < 5:
        return candidates[:keep_count]
    ranked = sorted(candidates, key=_kept_score, reverse=True)
    spoofs = [item for item in ranked if is_brand_spoof(item)]
    puns = [item for item in ranked if line_is_pun(item) and not is_brand_spoof(item)]
    chosen: list = []
    chosen_ids: set[int] = set()

    def take(pool: list, count: int) -> None:
        left = count
        for item in pool:
            if left <= 0 or len(chosen) >= keep_count:
                return
            if id(item) in chosen_ids:
                continue
            chosen.append(item)
            chosen_ids.add(id(item))
            left -= 1

    take(spoofs, 2)
    pun_have = sum(1 for item in chosen if line_is_pun(item) or is_brand_spoof(item))
    take(puns, max(0, 3 - pun_have))
    take(ranked, keep_count - len(chosen))
    return chosen


def brand_spoofs_needed(keep_count: int, spoof_count: int) -> int:
    """A final batch of five must include two major-brand logo spoofs."""

    if keep_count < 5:
        return 0
    return max(0, 2 - spoof_count)


def puns_still_needed(keep_count: int, pun_count: int) -> int:
    """How many more puns a final batch of five still needs. Smaller batches are not forced."""

    if keep_count < 5:
        return 0
    return max(0, 3 - pun_count)


def _anchor_norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").casefold()))


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
            f'One real person is both "{first}" and "{second}". '
            "Stack those co-occurring traits. Do not write a scenario about the two groups meeting. "
            + shared
        )
    if named:
        return (
            f'The user named "{named}". Add one co-occurring atlas trait as a stack modifier, '
            "not as a second niche and not as a hobby scenario. "
            + shared
        )
    return (
        "Build one real person from 2 or 3 traits that co-occur in the atlas overlaps. "
        "Do not cross two separate niches into a scenario, and do not describe a job procedure. "
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
    insider_jargon: bool = Field(
        default=False,
        description=(
            "True when the joke needs vocabulary a random adult would not know. "
            "A universal hook such as Karen or printer hell is not insider jargon."
        ),
    )
    trait_count: int = Field(
        default=0,
        ge=0,
        le=6,
        description="How many true identity traits the line stacks. 2 or 3 is the original shape.",
    )
    fresh_twist: bool = Field(
        default=False,
        description="True only when the line adds a turn a tired trope does not already have.",
    )
    plain_reading: str = Field(
        default="A member of this group would recognize the situation.",
        description="One sentence a random adult would think the line means. Empty if it is unclear.",
    )
    can_explain: bool = Field(
        default=True,
        description="False when a random adult would not know what the line means.",
    )
    words_earn_their_place: bool = Field(
        default=True,
        description=(
            "False when a word is random filler disconnected from the joke. "
            "Outside words are fine when everyone knows them and they serve the setup or punchline."
        ),
    )
    word_image_synergy: float = Field(
        default=8,
        ge=1,
        le=10,
        description=(
            "Do the words and the picture make one joke? "
            "Under 7 if the line works alone or the picture only illustrates the words."
        ),
    )
    pun_lands: bool = Field(
        default=True,
        description="False when the target group would not get the pun or spoof in 2 seconds.",
    )
    pun_forced: bool = Field(
        default=False,
        description="True when the pun is only a groan and the second meaning does not land.",
    )
    literal_image: bool = Field(
        default=False,
        description="True when the picture only illustrates the words and adds no twist.",
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
        insider_jargon: bool = False,
        trait_count: int = 0,
        fresh_twist: bool = False,
        tired_trope: bool = False,
        plain_reading: str = "A member of this group would recognize the situation.",
        can_explain: bool = True,
        words_earn_their_place: bool = True,
        filler_contrast: bool = False,
        word_image_synergy: float = 8,
        pun_lands: bool = True,
        pun_forced: bool = False,
        literal_image: bool = False,
    ):
        self.index = index
        self.humor_landed = humor_landed
        self.novelty = novelty
        self.tone_match = tone_match
        self.giftability = giftability
        self.reddit_upvote_score = reddit_upvote_score
        self.sticker_buy_score = sticker_buy_score
        self.instantly_understandable = instantly_understandable
        self.insider_jargon = insider_jargon
        self.trait_count = trait_count
        self.fresh_twist = fresh_twist
        self.tired_trope = tired_trope
        self.plain_reading = plain_reading
        self.can_explain = can_explain
        self.words_earn_their_place = words_earn_their_place
        self.filler_contrast = filler_contrast
        self.word_image_synergy = word_image_synergy
        self.pun_lands = pun_lands
        self.pun_forced = pun_forced
        self.literal_image = literal_image


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


_INSIDER_JARGON = ("patch tuesday", "boss pull", "raid night", "nerfed", "rmm", "vpn")


def needs_insider_vocabulary(text: str) -> bool:
    """A line whose joke requires words a random adult would not know.

    A universal hook such as Karen or printer hell can land inside a niche, so those
    lines are not capped as jargon.
    """

    lowered = " ".join(str(text or "").casefold().split())
    if re.search(r"\bkaren\b", lowered) or re.search(r"\bprinter\b", lowered):
        return False
    return any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in _INSIDER_JARGON)


def apply_jargon_cap(review, text: str):
    """Cap a jargon line at 5. Universal hooks keep the score the critic gave them."""

    if review is None:
        return review
    jargon = bool(getattr(review, "insider_jargon", False)) or needs_insider_vocabulary(text)
    if not jargon:
        return review
    review.insider_jargon = True
    for name in (
        "humor_landed",
        "sticker_buy_score",
        "instantly_understandable",
        "reddit_upvote_score",
    ):
        value = getattr(review, name, None)
        if value is not None and float(value) > 5:
            setattr(review, name, 5.0)
    return review


_ABSTRACT_HALVES = {
    "patience",
    "sanity",
    "love",
    "hope",
    "luck",
    "talent",
    "mood",
    "vibe",
    "soul",
    "energy",
}
# Disconnected filler. Common words that serve a punchline are not on this list.
_DISCONNECTED_FILLER = {"teleportation", "teleport", "speedrunner", "speedrunners", "ridgid"}
_CONTRAST_STOP = {"a", "an", "the", "my", "her", "his", "is", "isnt", "isn't", "not", "of", "in", "to", "and"}


def _cap_scores(review, ceiling: float, names: tuple[str, ...]) -> None:
    for name in names:
        value = getattr(review, name, None)
        if value is not None and float(value) > ceiling:
            setattr(review, name, float(ceiling))


def is_disconnected_filler(text: str) -> bool:
    """An outside concept used as random filler, not a word that earns its place."""

    tokens = set(re.findall(r"[a-z0-9']+", str(text or "").casefold()))
    return bool(tokens & _DISCONNECTED_FILLER)


def is_filler_contrast(text: str) -> bool:
    """The 'X is [adj]. My Y isn't.' template, unless both halves are concrete."""

    cleaned = " ".join(str(text or "").split())
    match = re.search(
        r"^(?P<left>.+?\bis\b.+?)\.\s+my\s+(?P<right>.+?)\s+isn't\.?$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match is None:
        return False

    def concrete(side: str) -> bool:
        tokens = [
            token
            for token in re.findall(r"[a-z0-9']+", side.casefold())
            if token not in _CONTRAST_STOP
        ]
        if any(token in _ABSTRACT_HALVES or token in _DISCONNECTED_FILLER for token in tokens):
            return False
        return any(len(token) >= 3 for token in tokens)

    return not (concrete(match.group("left")) and concrete(match.group("right")))


def reading_failed(review) -> bool:
    """True when the critic cannot say what a random adult would think the line means."""

    if review is None:
        return False
    if getattr(review, "can_explain", True) is False:
        return True
    reading = getattr(review, "plain_reading", None)
    if reading is None:
        return False
    text = str(reading).strip()
    if not text:
        return True
    return text.casefold() in {"unclear", "i don't know", "i dont know", "no idea"}


def apply_line_caps(review, text: str):
    """Cap filler contrasts at 5 and disconnected filler at 4. Do not cap a word that serves the joke."""

    if review is None:
        return review
    if is_disconnected_filler(text) or getattr(review, "words_earn_their_place", True) is False:
        review.words_earn_their_place = False
        _cap_scores(
            review,
            4,
            ("humor_landed", "sticker_buy_score", "instantly_understandable", "reddit_upvote_score"),
        )
    if is_filler_contrast(text):
        review.filler_contrast = True
        _cap_scores(review, 5, ("humor_landed", "sticker_buy_score", "reddit_upvote_score"))
    if reading_failed(review):
        review.can_explain = False
        _cap_scores(review, 3, ("instantly_understandable",))
        _cap_scores(review, 4, ("sticker_buy_score", "humor_landed"))
    if synergy_failed(review):
        _cap_scores(review, 4, ("humor_landed", "sticker_buy_score", "reddit_upvote_score"))
    return review


_PUN_PATTERNS = {
    "wordplay pun",
    "image pun",
    "celebrity food pun",
    "brand logo spoof",
    "innocent image innuendo",
    "cute but menacing",
    "dark twist scene",
    "catchphrase flip",
    "relatable confession action",
    "pop culture quote flip",
    "historical name pun",
    "fake acronym org",
    "fake warning sign",
    "slogan twist",
    "rhyme innuendo",
    "holiday pun",
    "name swap",
}


def pattern_key(candidate) -> str:
    """Normalize a pattern id so pun shapes match with spaces or underscores."""

    raw = str(getattr(candidate, "pattern", "") or "")
    return " ".join(raw.casefold().replace("_", " ").replace("-", " ").split())


def line_is_pun(candidate) -> bool:
    """A word pun, image pun, or spoof. The picture is half of the joke."""

    pattern = pattern_key(candidate)
    if pattern in _PUN_PATTERNS or "pun" in pattern or "spoof" in pattern:
        return True
    mechanism = str(getattr(candidate, "humor_mechanism", "") or "").casefold()
    return bool(re.search(r"\b(pun|puns|wordplay|spoof|spoofs|double meaning)\b", mechanism))


def synergy_failed(review) -> bool:
    """The picture does not complete the joke, or it only illustrates the words."""

    if review is None:
        return False
    if getattr(review, "literal_image", False) is True:
        return True
    score = getattr(review, "word_image_synergy", None)
    if score is None:
        return False
    try:
        return float(score) < 7
    except (TypeError, ValueError):
        return False


def apply_pun_cap(review, candidate):
    """Cap a groan or an obscure pun. A clear pun keeps the score the critic gave it."""

    if review is None or not line_is_pun(candidate):
        return review
    forced = getattr(review, "pun_forced", False) is True
    lands = getattr(review, "pun_lands", True) is not False
    if forced or not lands:
        _cap_scores(
            review,
            4,
            ("humor_landed", "sticker_buy_score", "instantly_understandable", "reddit_upvote_score"),
        )
    return review


def line_is_primary_wit(candidate) -> bool:
    """Sarcasm, irony, wit, or a pun. An identity stack alone is the secondary mode."""

    if line_is_pun(candidate):
        return True
    turn = str(getattr(candidate, "comic_turn", "") or "").casefold()
    mechanism = str(getattr(candidate, "humor_mechanism", "") or "").casefold()
    if turn in {"ironic", "sarcastic", "sarcasm"}:
        return True
    return any(
        word in mechanism
        for word in ("understatement", "reversal", "wordplay", "irony", "sarcasm", "wit")
    )


def pun_share(candidates: list) -> float:
    """Share of a batch that is a pun or spoof."""

    if not candidates:
        return 1.0
    return sum(1 for item in candidates if line_is_pun(item)) / len(candidates)


def pun_share_is_thin(candidates: list) -> bool:
    """A large batch under about 30 percent puns needs another pass. It does not fail the run."""

    return len(candidates) >= 6 and pun_share(candidates) < 0.3


def primary_wit_share(candidates: list) -> float:
    """Share of a batch whose comic turn is sarcasm, irony, or wit."""

    if not candidates:
        return 1.0
    return sum(1 for item in candidates if line_is_primary_wit(item)) / len(candidates)


_ROLE_WORDS = (
    "dad",
    "dads",
    "mom",
    "moms",
    "grandpa",
    "grandpas",
    "grandma",
    "grandmas",
    "nurse",
    "nurses",
    "mortician",
    "morticians",
    "daughter",
    "daughters",
    "farmer",
    "farmers",
    "pastor",
    "pastors",
    "widow",
    "widows",
    "trucker",
    "truckers",
    "deacon",
    "deacons",
    "retiree",
    "retirees",
)
_MODIFIER_WORDS = ("divorced", "rizzless", "swiftie", "feral", "night", "therapy", "girl", "hot")


def _stem(word: str) -> str:
    token = word.casefold().strip()
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def _role_stems(text: str) -> set[str]:
    lowered = text.casefold()
    return {_stem(word) for word in _ROLE_WORDS if re.search(rf"\b{re.escape(word)}\b", lowered)}


def stacked_trait_count(text: str) -> int:
    """How many traits are visible. Two or three is the shape that stayed original."""

    lowered = text.casefold()
    points = 0
    if _role_stems(text):
        points += 1
    modifiers = [word for word in _MODIFIER_WORDS if re.search(rf"\b{re.escape(word)}\b", lowered)]
    points += min(len(modifiers), 2)
    if re.search(r"\([^)]{3,}\)", text) or re.search(r"\bwho\b", lowered):
        points += 1
    if points <= 1:
        return points
    return min(points, 3)


def _cue_hit(text: str, trope: dict) -> bool:
    lowered = " ".join(text.casefold().split())
    return any(cue.casefold() in lowered for cue in trope.get("cues") or [])


def _second_identity(text: str, tropes: list[dict]) -> bool:
    owned = {_stem(name) for trope in tropes for name in trope.get("identities") or []}
    return any(stem not in owned for stem in _role_stems(text))


def _fresh_twist_text(text: str, tropes: list[dict]) -> bool:
    if re.search(r"\([^)]{3,}\)", text):
        return True
    if re.search(r"[\"“”].{2,}[\"“”]", text):
        return True
    lowered = text.casefold()
    for trope in tropes:
        for cue in trope.get("cues") or []:
            index = lowered.find(cue.casefold())
            if index < 0:
                continue
            after = lowered[index + len(cue) :]
            if re.search(r"\b(actually|but|except|unless)\b", after):
                return True
    return False


def escapes_tired_trope(text: str, tropes: list[dict], review=None) -> bool:
    """A second identity or a real twist keeps a familiar idea from being only the trope."""

    if _second_identity(text, tropes) or _fresh_twist_text(text, tropes):
        return True
    if review is not None and getattr(review, "fresh_twist", False):
        leftover = text.casefold()
        for trope in tropes:
            for cue in trope.get("cues") or []:
                leftover = leftover.replace(cue.casefold(), " ")
        extra = [token for token in re.findall(r"[a-z0-9']+", leftover) if len(token) > 3]
        return len(extra) >= 2
    return False


def apply_trope_cap(review, text: str, tropes: list[dict] | None = None):
    """Cap a single tired trope at 6. A stacked line or a fresh twist keeps its score."""

    if review is None or not tropes:
        return review
    matched = [trope for trope in tropes if _cue_hit(text, trope)]
    if not matched or escapes_tired_trope(text, matched, review):
        return review
    review.tired_trope = True
    for name in ("humor_landed", "sticker_buy_score", "reddit_upvote_score"):
        value = getattr(review, name, None)
        if value is not None and float(value) > 6:
            setattr(review, name, 6.0)
    return review


def tired_trope_block(tropes: list[dict] | None) -> str:
    """Tell the critic which single-identity jokes are already sold everywhere."""

    if not tropes:
        return ""
    labels = "; ".join(str(trope.get("label") or trope.get("id") or "") for trope in tropes[:8])
    return (
        "Tired tropes, already sold as single-identity jokes: "
        f"{labels}. A line that is only one of these scores at most 6 unless it stacks "
        "a second identity or a fresh twist. Stacking 2 or 3 true traits is the original "
        "shape and should score higher. Set trait_count to how many traits the line stacks. "
        "Set fresh_twist true only when the line adds a turn the trope does not already have.\n"
    )


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
                "Score only pairs from this bank. The bank is already weighted by buyer pride "
                "and broad appeal. Do not add a pair that is not listed, and do not cross a "
                "narrow occupation with a hobby.\n"
                f"{rendered}\n"
            )
    else:
        bank_lines = (
            "No identity-atlas bank was loaded. Choose broad identities only: body, age, "
            "family, faith, region, vice, or personality. Do not cross a narrow occupation "
            "with a hobby.\n"
        )
    return (
        "Propose about 10 stacks for die-cut stickers. "
        "Each stack is 2 or 3 traits that co-occur in one real person, taken from the atlas bank. "
        "Do not invent a job crossed with a hobby, and do not describe a scenario. "
        "A good stack is traits one person actually lives: body, age, family, "
        "faith, region, vice, or personality. "
        "The traits must co-occur in a real group. Never propose a random combo. "
        "Do not prefer dads, nurses, or morticians. Cover identities that have not been used. "
        "Do not propose a narrow occupation crossed with a hobby.\n"
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
        text = str(getattr(candidate, "artwork_text", "") or "")
        apply_jargon_cap(review, text)
        apply_line_caps(review, text)
        apply_pun_cap(review, candidate)
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
        if line_is_pun(candidate) and not synergy_failed(review):
            score += 2
        if review is None or not getattr(review, "tired_trope", False):
            traits = int(getattr(review, "trait_count", 0) or 0)
            if traits <= 0:
                traits = stacked_trait_count(str(getattr(candidate, "artwork_text", "") or ""))
            if 2 <= traits <= 3:
                score += 3
        if member_would_not_buy(review):
            continue
        if (
            str(getattr(candidate, "comic_turn", "") or "").casefold() == "straight"
            and not line_is_pun(candidate)
        ):
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
