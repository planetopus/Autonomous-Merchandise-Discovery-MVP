"""Social behavior to merchandise-text pipeline contract.

This pipeline intentionally collapses discovery into one provider call: OpenAI searches the
selected public social domains, extracts concrete lived behavior, and proposes text-first
merchandise copy. The domain module owns the structured contract and validation; the application
layer owns provider injection and persistence.
"""

from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from merchandise_discovery.domain.humor import (
    HumorExampleRecord,
    LineReviewRecord,
    NichePairRecord,
    PlaybookPatternRecord,
    humor_prompt_suffix,
    niche_pair_block,
    quote_block,
)
from merchandise_discovery.domain.models.common import HumorTone, SocialSource
from merchandise_discovery.domain.sticker_direction import (
    STICKER_AVOID,
    STICKER_STYLE_DIRECTION,
    crossover_block,
    sticker_copy_rules,
    sticker_visual_rules,
)


class SocialBehaviorTextInput(BaseModel):
    """User-defined social search scope and output bound for one run."""

    sources: list[SocialSource] = Field(min_length=1)
    query: str = Field(default="", max_length=500)
    auto_topic: bool = False
    candidate_count: int = Field(ge=1, le=25)
    niche_a: str = Field(default="", max_length=500)
    niche_b: str = Field(default="", max_length=500)
    humor_tone: HumorTone = HumorTone.DRY

    @model_validator(mode="after")
    def validate_topic_source(self) -> "SocialBehaviorTextInput":
        """Require a manual topic only when the user has not delegated topic selection to AI."""

        if not self.auto_topic and len(self.query.strip()) < 3:
            raise ValueError("query must contain at least 3 characters unless auto_topic is enabled")
        return self


class SocialBehaviorTextCandidate(BaseModel):
    """One source-backed behavior and the merchandise text derived from it."""

    source_platform: SocialSource
    source_url: str = Field(min_length=1)
    source_title: str = Field(min_length=1, max_length=300)
    source_excerpt: str = Field(min_length=1, max_length=2_000)
    audience_context: str = Field(min_length=1, max_length=500)
    behavior: str = Field(min_length=1, max_length=500)
    friction_or_pressure: str = Field(min_length=1, max_length=500)
    # Sticker lines are short labels. Empty text is an image-only sticker.
    artwork_text: str = Field(default="", max_length=160)
    # Stage 2 consumes this exact prompt. Keeping it beside the copy makes the first stage the
    # durable source of truth for the visual direction instead of re-deriving it downstream.
    artwork_prompt: str = Field(min_length=20, max_length=4_000)
    visual_punchline: str = Field(min_length=1, max_length=500)
    main_visual_metaphor: str = Field(min_length=1, max_length=500)
    audience_specific_cue: str = Field(min_length=1, max_length=500)
    tone: str = Field(min_length=1, max_length=200)
    style_direction: str = Field(min_length=1, max_length=500)
    things_to_avoid: list[str] = Field(min_length=1, max_length=10)
    specificity_reason: str = Field(min_length=1, max_length=700)
    source_quote: str = Field(default="", max_length=500)
    humor_mechanism: str = Field(default="", max_length=200)
    concrete_detail: str = Field(default="", max_length=200)
    pattern: str = Field(default="", max_length=80)
    truth: str = Field(default="", max_length=160)
    comic_turn: str = Field(default="straight", max_length=20)
    funny_score: float | None = Field(default=None, ge=0, le=10)

    @field_validator("source_url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        """Reject fabricated non-web references while allowing provider-specific URL shapes."""

        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an absolute HTTP(S) URL")
        return value


class SocialBehaviorTextOutput(BaseModel):
    """Complete structured response returned by the single social discovery call."""

    candidates: list[SocialBehaviorTextCandidate] = Field(min_length=1, max_length=30)
    search_summary: str = Field(min_length=1, max_length=2_000)
    topic_explored: str = Field(default="", max_length=500)
    model: str = "deterministic"
    humor_examples_used: list[HumorExampleRecord] = Field(default_factory=list)
    humor_themes_used: list[str] = Field(default_factory=list)
    niche_pair_a: str = Field(default="", max_length=200)
    niche_pair_b: str = Field(default="", max_length=200)
    pairing_score: float | None = Field(default=None, ge=0, le=10)
    pairing_reason: str = Field(default="", max_length=500)
    line_reviews: list[LineReviewRecord] = Field(default_factory=list)
    niche_pair_candidates: list[NichePairRecord] = Field(default_factory=list)
    humor_playbook_used: list[PlaybookPatternRecord] = Field(default_factory=list)
    stage_warning: str = ""


def reasoning_instructions(tone: HumorTone | str = HumorTone.DRY) -> str:
    """Return the provider contract for standalone, concrete, audience-recognizable copy."""

    return (
        "You are a merchandise discovery researcher and die-cut vinyl sticker creative director. "
        "Use the supplied "
        "web search tool to inspect public discussions from the requested Reddit and/or X domains. "
        "Extract concrete repeated behavior, not broad labels or demographic stereotypes. Look for "
        "the small lived action, routine, contradiction, friction, or ordinary pressure that an "
        "insider would recognize. Then write one original merchandise line for each behavior. "
        "The merchandise line is the primary product output and MUST make sense when read alone, "
        "without the observed behavior, friction, or specificity fields. It should make the target "
        "person think 'that is literally me'. "
        f"{sticker_copy_rules()} Preserve the personal relationship, concrete object, or exact "
        "action that makes the behavior recognizable, but compress it into the short sticker line "
        "instead of narrating it. If a pronoun such as 'she', 'he', or 'they' would be unclear, "
        "name the person or relationship inside those few words or drop the text. Do not force "
        "every line into an 'I ...' template. This is sticker merchandise: do not let the visual "
        "prompt rewrite the copy. Alongside the merchandise line, write an `artwork_prompt` for "
        "Grok. The prompt must render the exact merchandise line when one is present, or no text "
        "when artwork_text is empty, and preserve the audience and behavior with one isolated "
        f"subject. {sticker_visual_rules()} The artwork prompt is not a replacement for the "
        "merchandise line: it is the visual execution brief for that exact line. Preserve source "
        "URLs and provide a source-specific excerpt. Return only the requested structured output. "
        f"{humor_prompt_suffix(tone)}"
    )


def build_user_prompt(
    input_model: SocialBehaviorTextInput,
    *,
    draft_count: int | None = None,
    quotes: list | None = None,
    humor_reference_block: str = "",
) -> str:
    """Build the single-call request from user scope and source-domain instructions."""

    platforms = ", ".join(source.value for source in input_model.sources)
    topic_instruction = (
        "Choose the behavior or topic yourself before searching. Select a narrow, distinct everyday "
        "behavior with a recognizable tension, contradiction, absurdity, or private joke. Avoid "
        "broad demographics, product categories, generic trends, and soft self-care routines with "
        "no sharp angle. Return the chosen topic in "
        "`topic_explored`."
        if input_model.auto_topic
        else f"Behavior/topic to investigate: {input_model.query}"
    )
    limit = draft_count or input_model.candidate_count
    draft_note = ""
    if draft_count and draft_count > input_model.candidate_count:
        draft_note = (
            f"Generate {draft_count} distinct lines so a separate critic can cut most of them.\n"
        )
    return (
        f"{humor_prompt_suffix(input_model.humor_tone)}\n"
        f"{humor_reference_block}"
        f"{quote_block(quotes)}"
        f"{draft_note}"
        f"{niche_pair_block(input_model.niche_a, input_model.niche_b)}"
        f"{crossover_block(input_model.niche_a, input_model.niche_b)}"
        f"Search these public platforms: {platforms}.\n"
        f"{topic_instruction}\n"
        f"Return up to {limit} distinct behavior-based merchandise text "
        "candidates. Avoid repeating the same audience pressure or behavior in different wording. "
        "Before returning each line, check that a reader can understand the joke without any other "
        "field. Write a joke-shaped line of about 4 to 14 words, or leave artwork_text empty "
        "for an image-only sticker. Use the real relationship, behavior, or object instead of a "
        "generic slogan, but do not write a sentence. For every candidate also provide an "
        "artwork_prompt that tells Grok how to render one isolated subject for this audience on "
        "a plain white background. Also provide visual_punchline, main_visual_metaphor, "
        "audience_specific_cue, tone, style_direction, and a things_to_avoid list. The visual "
        "punchline must exaggerate the insider behavior rather than literally illustrate a "
        "bedroom, clock, meal, couch, scene, or landscape. The style direction must describe a "
        "flat vector die-cut vinyl sticker: bold clean outlines, flat colors, one centered "
        "isolated subject, and a plain white background. things_to_avoid must include a scene or "
        "landscape, a full-bleed background, realistic shading, and a poster layout. Each "
        "candidate must cite one directly relevant source URL. Also return the final behavior or "
        "topic you actually explored in `topic_explored` from the searched platforms."
    )


def _remember_quote(candidate: SocialBehaviorTextCandidate) -> SocialBehaviorTextCandidate:
    """Keep a verbatim quote on the candidate even when the model only filled the excerpt."""

    if candidate.source_quote.strip():
        return candidate
    return candidate.model_copy(update={"source_quote": candidate.source_excerpt[:500]})


def execute(
    input_model: SocialBehaviorTextInput,
    *,
    reasoning_output: SocialBehaviorTextOutput | None = None,
    model: str = "deterministic",
) -> SocialBehaviorTextOutput:
    """Validate live output or produce an explicit fixture result for local demos."""

    if reasoning_output is not None:
        if len(reasoning_output.candidates) > input_model.candidate_count:
            raise ValueError(
                "Social behavior provider returned more candidates than the configured limit."
            )
        allowed_sources = set(input_model.sources)
        invalid_sources = [
            candidate.source_platform.value
            for candidate in reasoning_output.candidates
            if candidate.source_platform not in allowed_sources
        ]
        if invalid_sources:
            raise ValueError(
                "Social behavior provider returned candidates from unrequested sources: "
                + ", ".join(sorted(set(invalid_sources)))
            )
        for candidate in reasoning_output.candidates:
            hostname = (urlparse(candidate.source_url).hostname or "").lower()
            if candidate.source_platform == SocialSource.REDDIT:
                valid_domain = hostname == "reddit.com" or hostname.endswith(".reddit.com")
            else:
                valid_domain = hostname in {"x.com", "twitter.com"} or hostname.endswith(
                    (".x.com", ".twitter.com")
                )
            if not valid_domain:
                raise ValueError(
                    f"Social behavior provider cited {candidate.source_url!r} for "
                    f"{candidate.source_platform.value}; expected the selected platform domain."
                )
        return reasoning_output.model_copy(
            update={
                "model": model,
                "topic_explored": reasoning_output.topic_explored or input_model.query,
                "candidates": [_remember_quote(candidate) for candidate in reasoning_output.candidates],
            }
        )

    source = input_model.sources[0]
    effective_query = input_model.query.strip() or (
        "people turning small daily frustrations into personal routines"
    )
    candidates = [
        SocialBehaviorTextCandidate(
            source_platform=source,
            source_url=f"https://fixture.local/{source.value}/behavior/{index}",
            source_title=f"Fixture {source.value} behavior {index}",
            source_excerpt=(
                f"Fixture discussion about the behavior described by: {effective_query}."
            ),
            audience_context=effective_query,
            behavior=f"People repeatedly describe the routine of {effective_query}.",
            friction_or_pressure="The routine collides with the ordinary pressure of keeping daily life moving.",
            artwork_text="Still Doing It",
            artwork_prompt=(
                "Create a die-cut vinyl sticker with one isolated subject for the line "
                '"Still Doing It". Flat vector shapes, bold outlines, flat colors, plain white '
                "background, no scene, logos, or extra text."
            ),
            visual_punchline=(
                "The ordinary routine is treated as an overdramatic personal rule that protects "
                "the wearer from daily chaos."
            ),
            main_visual_metaphor=(
                "A small everyday object becomes an exaggerated guardian of the routine."
            ),
            audience_specific_cue=effective_query,
            tone="dry, self-aware, and mildly absurd",
            style_direction=STICKER_STYLE_DIRECTION,
            things_to_avoid=[
                "soft lifestyle photography",
                "generic decorative props",
                "extra text",
                *STICKER_AVOID,
            ],
            specificity_reason="Fixture output only; replace with live source-backed behavior in live mode.",
            source_quote=f"Fixture comment about the routine of {effective_query}.",
            humor_mechanism="recognition",
            concrete_detail=effective_query[:200],
        )
        for index in range(1, input_model.candidate_count + 1)
    ]
    return SocialBehaviorTextOutput(
        candidates=candidates,
        search_summary="Deterministic fixture output; no social platform was queried.",
        topic_explored=effective_query,
        model=model,
    )
