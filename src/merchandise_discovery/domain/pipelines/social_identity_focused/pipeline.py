"""Identity-focused social discussions to merchandise-text pipeline contract.

This is deliberately a separate contract from ``social_behavior_text``. Both pipelines search the
same public sources and generate the same two output kinds, but this variant makes an explicit
identity a first-class input and validates that every candidate preserves it. That separation keeps
the original social pipeline as an honest A/B control instead of silently changing its behavior.
"""

from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from merchandise_discovery.domain.humor import (
    HumorExampleRecord,
    LineReviewRecord,
    NichePairRecord,
    PlaybookPatternRecord,
    broad_identity_brief,
    humor_prompt_suffix,
    niche_pair_block,
    quote_block,
)
from merchandise_discovery.domain.models.common import (
    HumorTone,
    IdentityType,
    SocialSource,
    identity_type_guidance,
)
from merchandise_discovery.domain.sticker_direction import (
    STICKER_AVOID,
    STICKER_STYLE_DIRECTION,
    crossover_block,
    sticker_copy_rules,
    sticker_visual_rules,
)


class SocialIdentityTextInput(BaseModel):
    """User-defined source scope, identity anchor, and output bound for one run."""

    sources: list[SocialSource] = Field(min_length=1)
    identity: str = Field(default="", max_length=300)
    identity_type: IdentityType | None = None
    auto_identity: bool = False
    query: str = Field(default="", max_length=500)
    auto_topic: bool = False
    candidate_count: int = Field(ge=1, le=25)
    niche_a: str = Field(default="", max_length=500)
    niche_b: str = Field(default="", max_length=500)
    humor_tone: HumorTone = HumorTone.DRY
    recent_identity_selections: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("identity")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        """Reject whitespace-only identity anchors before they reach a provider prompt."""

        return value.strip()

    @model_validator(mode="after")
    def validate_topic_source(self) -> "SocialIdentityTextInput":
        """Require a manual topic only when the user has not delegated discovery to AI."""

        if not self.auto_identity and len(self.identity) < 2:
            raise ValueError("identity must contain at least 2 characters unless auto_identity is enabled")
        if not self.auto_identity and self.identity_type is None:
            raise ValueError("identity_type is required unless auto_identity is enabled")
        if not self.auto_topic and len(self.query.strip()) < 3:
            raise ValueError("query must contain at least 3 characters unless auto_topic is enabled")
        return self


class SocialIdentityTextCandidate(BaseModel):
    """One source-backed identity behavior and the merchandise direction derived from it."""

    identity: str = Field(min_length=2, max_length=300)
    identity_type: IdentityType
    identity_evidence: str = Field(min_length=1, max_length=700)
    source_platform: SocialSource
    source_url: str = Field(min_length=1)
    source_title: str = Field(min_length=1, max_length=300)
    source_excerpt: str = Field(min_length=1, max_length=2_000)
    audience_context: str = Field(min_length=1, max_length=500)
    behavior: str = Field(min_length=1, max_length=500)
    friction_or_pressure: str = Field(min_length=1, max_length=500)
    artwork_text: str = Field(default="", max_length=160)
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
    who_its_for: list[str] = Field(default_factory=list, max_length=4)
    funny_score: float | None = Field(default=None, ge=0, le=10)

    @field_validator("source_url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        """Reject fabricated non-web references while allowing provider-specific URL shapes."""

        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an absolute HTTP(S) URL")
        return value


class SocialIdentityTextOutput(BaseModel):
    """Complete structured response returned by the identity-focused social call."""

    identity_selected: str = Field(default="", max_length=300)
    identity_type_selected: IdentityType | None = None
    candidates: list[SocialIdentityTextCandidate] = Field(min_length=1, max_length=30)
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
    """Return the provider contract that makes identity preservation non-optional."""

    return (
        "You are a merchandise discovery researcher and die-cut vinyl sticker creative director. "
        "Use the supplied web search tool to inspect public Reddit and/or X discussions, but treat "
        "the user-supplied identity as a hard audience anchor. Do not replace it with a broad "
        "demographic, invent an identity, or infer sensitive traits. Extract concrete behavior, "
        "friction, contradiction, ritual, or private joke that is recognizably experienced by that "
        "identity. Use source evidence as seasoning. Do not let one narrow policy or incident "
        "define every line. If the identity is not supplied, first consider several concrete, non-sensitive "
        "identities across the available identity types. Choose the "
        "most distinctive identity with repeated source evidence, not the most familiar profession "
        "or the easiest audience to write for. Avoid repeating recent selections unless the source "
        f"evidence reveals a materially different identity. Identity type guide: {identity_type_guidance()}. "
        "Return the selected identity in "
        "`identity_selected` and its type in `identity_type_selected`. Every "
        "merchandise line and artwork prompt must preserve the identity naturally, "
        "so the target person thinks 'that is literally me' rather than merely seeing a generic joke. "
        f"{sticker_copy_rules()} Use a concrete role-specific duty, tool, setting, relationship, "
        "object, time, or exact action when supported by the source, compressed into the short "
        "sticker line. Do not force an 'I ...' template. Alongside the copy, create a Grok "
        "artwork prompt that renders the exact line when text is present and visibly identifies "
        "the supplied identity through one identity-specific cue and one visual joke. "
        f"{sticker_visual_rules()} Preserve source URLs and source-specific excerpts. Return only "
        f"the requested structured output. {humor_prompt_suffix(tone)}"
    )


def build_user_prompt(
    input_model: SocialIdentityTextInput,
    *,
    draft_count: int | None = None,
    quotes: list | None = None,
    humor_reference_block: str = "",
) -> str:
    """Build a provider request that repeats the identity anchor at every important decision."""

    platforms = ", ".join(source.value for source in input_model.sources)
    identity_instruction = (
        "The niche pair in this prompt is the audience. If the user did not name two niches, "
        "choose two different niches that share a life before choosing the behavior, and set "
        "`identity_selected` to niche_pair_a. Compare several source-backed identities across "
        "different identity types and name the chosen audience naturally, as a person would "
        "describe themselves rather than as a bureaucratic research segment. Return it in "
        "`identity_selected` and classify it in "
        f"`identity_type_selected` using this taxonomy: {identity_type_guidance()}. "
        "Use only the allowed identity types; do not infer sensitive personal traits."
        if input_model.auto_identity
        else (
            f"Use this supplied identity exactly: {input_model.identity}. "
            f"Its identity type is {input_model.identity_type.value}."
        )
    )
    topic_instruction = broad_identity_brief("" if input_model.auto_topic else input_model.query)
    diversity_instruction = (
        "Before selecting the identity, internally compare several source-backed candidates across "
        "different identity types and prefer the most distinctive, underrepresented audience. Do "
        "not default to a familiar healthcare, education, or office profession merely because it has "
        "many search results. Recent identities to avoid repeating unless materially different: "
        + ", ".join(input_model.recent_identity_selections)
        + ".\n"
        if input_model.auto_identity
        else ""
    )
    identity_context = (
        ""
        if input_model.auto_identity
        else (
            f"Target identity: {input_model.identity}\n"
            f"Identity type: {input_model.identity_type.value}\n"
        )
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
        f"{niche_pair_block(input_model.niche_a, input_model.niche_b, input_model.identity)}"
        f"{crossover_block(input_model.niche_a, input_model.niche_b)}"
        f"{identity_instruction}\n"
        f"{identity_context}"
        f"Search these public platforms: {platforms}.\n"
        f"{diversity_instruction}"
        f"{topic_instruction}\n"
        f"Return up to {limit} distinct candidates. Each candidate must include "
        "identity evidence explaining why the source actually supports this identity, then one "
        "specific behavior and friction grounded in that identity. The merchandise text must be "
        "self-explanatory joke-shaped sticker copy of about 4 to 14 words, or empty when the sticker "
        "is image-only. Preserve the identity in that short line without requiring the metadata. "
        "Avoid repeating the same identity behavior in different wording. Also provide an "
        "artwork_prompt, visual_punchline, main_visual_metaphor, audience_specific_cue, tone, "
        "style_direction, and things_to_avoid. The visual cue must make the supplied identity "
        "recognizable without relying on a logo, institution, or invented uniform. Style direction "
        "must be a flat vector sticker: one centered subject, bold outlines, flat colors, plain "
        "white background. Cite one directly relevant source URL per candidate and return the "
        "actual topic in `topic_explored`."
    )


def _source_domain_is_valid(candidate: SocialIdentityTextCandidate) -> bool:
    """Check that a provider citation belongs to the platform it claims to represent."""

    hostname = (urlparse(candidate.source_url).hostname or "").lower()
    if candidate.source_platform == SocialSource.REDDIT:
        return hostname == "reddit.com" or hostname.endswith(".reddit.com")
    return hostname in {"x.com", "twitter.com"} or hostname.endswith((".x.com", ".twitter.com"))


def execute(
    input_model: SocialIdentityTextInput,
    *,
    reasoning_output: SocialIdentityTextOutput | None = None,
    model: str = "deterministic",
) -> SocialIdentityTextOutput:
    """Validate live output or produce an explicit fixture result for local demos."""

    if reasoning_output is not None:
        if len(reasoning_output.candidates) > input_model.candidate_count:
            raise ValueError("Identity-focused provider returned more candidates than configured.")
        selected_identity = (reasoning_output.identity_selected or input_model.identity).strip()
        selected_identity_type = reasoning_output.identity_type_selected or input_model.identity_type
        if not input_model.auto_identity:
            # Manual input is the user's source of truth; provider wording cannot replace it.
            selected_identity = input_model.identity.strip()
            selected_identity_type = input_model.identity_type
        if len(selected_identity) < 2 or selected_identity_type is None:
            raise ValueError(
                "Identity-focused provider must return identity_selected and "
                "identity_type_selected when identity is AI-selected."
            )
        allowed_sources = set(input_model.sources)
        normalized_candidates = []
        for candidate in reasoning_output.candidates:
            if candidate.source_platform not in allowed_sources:
                raise ValueError(
                    "Identity-focused provider returned a candidate from an unrequested source."
                )
            if not _source_domain_is_valid(candidate):
                raise ValueError(
                    f"Identity-focused provider cited {candidate.source_url!r} for "
                    f"{candidate.source_platform.value}; expected that platform domain."
                )
            # Persist one canonical identity label so downstream artwork and UI records do not
            # alternate between harmless provider typography variants.
            quoted = candidate
            if not candidate.source_quote.strip():
                quoted = candidate.model_copy(update={"source_quote": candidate.source_excerpt[:500]})
            normalized_candidates.append(
                quoted.model_copy(
                    update={
                        "identity": selected_identity,
                        "identity_type": selected_identity_type,
                    }
                )
            )
        return reasoning_output.model_copy(
            update={
                "model": model,
                "identity_selected": selected_identity,
                "identity_type_selected": selected_identity_type,
                "topic_explored": reasoning_output.topic_explored or input_model.query,
                "candidates": normalized_candidates,
            }
        )

    source = input_model.sources[0]
    effective_identity = input_model.identity.strip() or "night-shift workers"
    effective_identity_type = input_model.identity_type or IdentityType.OCCUPATION
    effective_query = input_model.query.strip() or (
        "a small daily behavior that reveals how this identity gets through ordinary life"
    )
    candidates = [
        SocialIdentityTextCandidate(
            identity=effective_identity,
            identity_type=effective_identity_type,
            identity_evidence=(
                f"Fixture identity anchor: {effective_identity} ({effective_identity_type.value})."
            ),
            source_platform=source,
            source_url=f"https://fixture.local/{source.value}/identity/{index}",
            source_title=f"Fixture {source.value} identity behavior {index}",
            source_excerpt=f"Fixture discussion about {input_model.identity}: {effective_query}.",
            audience_context=effective_identity,
            behavior=f"{effective_identity} repeatedly describes {effective_query}.",
            friction_or_pressure="The identity-specific routine collides with ordinary daily pressure.",
            artwork_text=" ".join(effective_identity.split()[:4]) or "Still Here",
            artwork_prompt=(
                f"Create a die-cut vinyl sticker for {effective_identity}. One isolated subject "
                f"about {effective_query}, flat colors, plain white background, no logos or extra text."
            ),
            visual_punchline="An ordinary identity-specific workaround is treated like a heroic operating rule.",
            main_visual_metaphor="A small object becomes an exaggerated tool of identity-specific survival.",
            audience_specific_cue=effective_identity,
            tone="dry, personal, and mildly absurd",
            style_direction=STICKER_STYLE_DIRECTION,
            things_to_avoid=["generic lifestyle imagery", "invented logos", "extra text", *STICKER_AVOID],
            specificity_reason="Fixture output only; replace with live source-backed identity evidence.",
            source_quote=f"Fixture comment about {effective_identity}.",
            humor_mechanism="recognition",
            concrete_detail=effective_identity[:200],
        )
        for index in range(1, input_model.candidate_count + 1)
    ]
    return SocialIdentityTextOutput(
        identity_selected=effective_identity,
        identity_type_selected=effective_identity_type,
        candidates=candidates,
        search_summary="Deterministic fixture output; no social platform was queried.",
        topic_explored=effective_query,
        model=model,
    )
