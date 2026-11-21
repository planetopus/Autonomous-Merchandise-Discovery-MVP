"""Stage 2 contract for turning social-behavior candidates into Grok image requests.

Stage 1 owns the reasoning: it extracts the behavior, writes the merchandise copy, and creates
the visual prompt. This module only validates that handoff and maps it to the shared image
generation contract, keeping provider and storage concerns outside the social pipeline.
"""

from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field

from merchandise_discovery.domain.pipelines.social_behavior_text.pipeline import (
    SocialBehaviorTextCandidate,
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
    finished_sticker_direction,
    merchandise_text_clause,
    merged_avoid_list,
    render_image_prompt,
)
from merchandise_discovery.infrastructure.providers.image_provider import ImageProvider
from merchandise_discovery.infrastructure.storage import ArtworkStorage


class SocialArtworkInput(BaseModel):
    """Stage 1 candidates and the number of images to create for each candidate."""

    candidates: list[SocialBehaviorTextCandidate] = Field(min_length=1, max_length=25)
    artwork_variants_per_candidate: int = Field(default=1, ge=1, le=3)
    niche_a: str = ""
    niche_b: str = ""


def _stable_id(run_id: str, source_url: str, index: int, kind: str) -> str:
    """Create repeatable artifact IDs so a retry replaces the same social candidate records."""

    return str(uuid5(NAMESPACE_URL, f"social-behavior:{run_id}:{source_url}:{index}:{kind}"))


def to_artwork_generation_input(
    input_model: SocialArtworkInput,
    *,
    run_id: str,
) -> ArtworkGenerationInput:
    """Map social candidates to the shared Grok generation input without changing their meaning."""

    prompts: list[PromptCompilation] = []
    for index, candidate in enumerate(input_model.candidates, start=1):
        prompt = build_targeted_artwork_prompt(
            candidate,
            niche_a=input_model.niche_a,
            niche_b=input_model.niche_b,
        )
        prompts.append(
            PromptCompilation(
                run_id=run_id,
                concept_id=_stable_id(run_id, candidate.source_url, index, "concept"),
                brief_id=_stable_id(run_id, candidate.source_url, index, "brief"),
                prompt=prompt,
                combination_name=candidate.artwork_text or "Image-only sticker",
                audience_label=" · ".join(candidate.who_its_for),
            )
        )
    return ArtworkGenerationInput(
        prompts=prompts,
        artwork_variants_per_concept=input_model.artwork_variants_per_candidate,
    )


def build_targeted_artwork_prompt(
    candidate: SocialBehaviorTextCandidate,
    *,
    niche_a: str = "",
    niche_b: str = "",
) -> str:
    """Compile AI creative direction into a strict die-cut sticker prompt for Grok.

    The model supplies the joke and audience insight. This wrapper keeps the image on one
    isolated subject with a plain background instead of a full-bleed shirt or poster.
    """

    rendered = render_image_prompt(candidate)
    if rendered:
        return rendered
    avoid = merged_avoid_list(candidate.things_to_avoid)
    return (
        f"{artwork_preamble()}\n"
        f"{crossover_block(niche_a, niche_b)}"
        "Use one dominant visual joke tied to the audience's specific behavior. Do not use "
        "soft gradients, cozy stock-photo lighting, generic bedroom/clock/meal/couch imagery, "
        "an infographic timeline, decorative filler, logos, brands, or extra text unless the "
        "creative direction explicitly transforms that object into the joke.\n\n"
        f"{merchandise_text_clause(candidate.artwork_text)}\n"
        f"Audience: {candidate.audience_context}\n"
        f"Audience-specific visual cue: {candidate.audience_specific_cue}\n"
        f"Visual punchline: {candidate.visual_punchline}\n"
        f"Main visual metaphor: {candidate.main_visual_metaphor}\n"
        f"Tone: {candidate.tone}\n"
        f"Style direction: {candidate.style_direction}\n"
        f"AI visual direction: {candidate.artwork_prompt}\n"
        f"Do not include: {avoid}\n"
        "The final sticker should make the target audience think: 'That is literally me.'\n"
        f"{finished_sticker_direction(candidate)}"
    )


def execute(
    input_model: SocialArtworkInput,
    *,
    run_id: str,
    provider: ImageProvider,
    storage: ArtworkStorage | None = None,
) -> ArtworkGenerationOutput:
    """Generate and persist social artwork through the shared provider-neutral stage contract."""

    return execute_artwork_generation(
        to_artwork_generation_input(input_model, run_id=run_id),
        provider,
        storage,
    )
