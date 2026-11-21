"""Stage 2 contract for identity-focused Grok artwork generation."""

from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field

from merchandise_discovery.domain.pipelines.social_identity_focused.pipeline import (
    SocialIdentityTextCandidate,
)
from merchandise_discovery.domain.stages.stage_14_prompt_compilation import PromptCompilation
from merchandise_discovery.domain.stages.stage_15_artwork_generation import (
    ArtworkGenerationInput,
    ArtworkGenerationOutput,
)
from merchandise_discovery.domain.stages.stage_15_artwork_generation import (
    execute as execute_artwork_generation,
)
from merchandise_discovery.domain.sticker_direction import (
    artwork_preamble,
    crossover_block,
    direct_image_prompt,
    finished_sticker_direction,
    merchandise_text_clause,
    merged_avoid_list,
    style_label,
)
from merchandise_discovery.infrastructure.providers.image_provider import ImageProvider
from merchandise_discovery.infrastructure.storage import ArtworkStorage


class IdentityArtworkInput(BaseModel):
    """Validated Stage 1 handoff and image count for the identity-focused variant."""

    candidates: list[SocialIdentityTextCandidate] = Field(min_length=1, max_length=25)
    artwork_variants_per_candidate: int = Field(default=1, ge=1, le=3)
    niche_a: str = ""
    niche_b: str = ""


def _stable_id(run_id: str, source_url: str, index: int, kind: str) -> str:
    """Create repeatable IDs so retries replace the same identity-focused artifacts."""

    return str(uuid5(NAMESPACE_URL, f"social-identity:{run_id}:{source_url}:{index}:{kind}"))


def build_identity_artwork_prompt(
    candidate: SocialIdentityTextCandidate,
    *,
    niche_a: str = "",
    niche_b: str = "",
) -> str:
    """Compile the identity anchor into the die-cut sticker handoff sent to Grok."""

    direct = direct_image_prompt(candidate)
    if direct:
        return direct
    avoid = merged_avoid_list(candidate.things_to_avoid)
    return (
        f"{artwork_preamble()}\n"
        f"{crossover_block(niche_a, niche_b)}"
        "The design must make the supplied identity visibly recognizable through the specific "
        "audience cue and behavior below, not through a generic demographic stereotype. Use one "
        "dominant visual joke. Do not invent logos, brands, uniforms, institutions, or extra text. "
        "Avoid generic bedroom, clock, meal, couch, or inspirational imagery unless transformed into "
        "the identity-specific joke.\n\n"
        f"{merchandise_text_clause(candidate.artwork_text)}\n"
        f"Target identity: {candidate.identity}\n"
        f"Identity type: {candidate.identity_type.value}\n"
        f"Identity evidence: {candidate.identity_evidence}\n"
        f"Audience-specific cue: {candidate.audience_specific_cue}\n"
        f"Observed behavior: {candidate.behavior}\n"
        f"Friction or pressure: {candidate.friction_or_pressure}\n"
        f"Visual punchline: {candidate.visual_punchline}\n"
        f"Main visual metaphor: {candidate.main_visual_metaphor}\n"
        f"Tone: {candidate.tone}\n"
        f"Style direction: {candidate.style_direction}\n"
        f"AI visual direction: {candidate.artwork_prompt}\n"
        f"Do not include: {avoid}\n"
        "The target identity should recognize the sticker immediately: 'That is literally me.'\n"
        f"{finished_sticker_direction(candidate)}"
    )


def to_artwork_generation_input(
    input_model: IdentityArtworkInput,
    *,
    run_id: str,
) -> ArtworkGenerationInput:
    """Map the identity candidate contract to the shared Grok generation boundary."""

    prompts = [
        PromptCompilation(
            run_id=run_id,
            concept_id=_stable_id(run_id, candidate.source_url, index, "concept"),
            brief_id=_stable_id(run_id, candidate.source_url, index, "brief"),
            prompt=build_identity_artwork_prompt(
                candidate,
                niche_a=input_model.niche_a,
                niche_b=input_model.niche_b,
            ),
            combination_name=candidate.artwork_text or "Image-only sticker",
            audience_label=" · ".join(candidate.who_its_for),
            style_label=style_label(candidate.style_direction),
        )
        for index, candidate in enumerate(input_model.candidates, start=1)
    ]
    return ArtworkGenerationInput(
        prompts=prompts,
        artwork_variants_per_concept=input_model.artwork_variants_per_candidate,
    )


def execute(
    input_model: IdentityArtworkInput,
    *,
    run_id: str,
    provider: ImageProvider,
    storage: ArtworkStorage | None = None,
) -> ArtworkGenerationOutput:
    """Generate identity-focused artwork through the existing provider/storage implementation."""

    return execute_artwork_generation(
        to_artwork_generation_input(input_model, run_id=run_id),
        provider,
        storage,
    )
