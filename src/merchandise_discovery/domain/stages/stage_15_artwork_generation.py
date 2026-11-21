"""Stage 15: generate artwork candidates through the injected image provider."""

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from merchandise_discovery.domain.models.artifacts import Artwork
from merchandise_discovery.domain.models.usage import UsageMetrics, combine_usage
from merchandise_discovery.domain.stages.stage_14_prompt_compilation import PromptCompilation
from merchandise_discovery.infrastructure.providers.image_provider import (
    ImageGenerationRequest,
    ImageProvider,
)
from merchandise_discovery.infrastructure.storage import (
    ArtworkStorage,
    ReferenceArtworkStorage,
)


class ArtworkGenerationInput(BaseModel):
    """Finalist prompts and the configured number of image variants per concept."""

    prompts: list[PromptCompilation]
    artwork_variants_per_concept: int = Field(ge=1, le=10)


class ArtworkGenerationOutput(BaseModel):
    """Generated artwork metadata linked to concept, brief, and prompt."""

    artworks: list[Artwork]
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    warning: str = ""


def _artwork_critique(prompt: PromptCompilation) -> dict:
    """Buyer groups and the art style travel with the image so the gallery can label it."""

    critique = {}
    if prompt.audience_label:
        critique["who_its_for"] = prompt.audience_label
    if prompt.combination_name:
        critique["expected_text"] = prompt.combination_name
    if prompt.style_label:
        critique["art_style"] = prompt.style_label
    return critique


def execute(
    input_data: ArtworkGenerationInput,
    provider: ImageProvider,
    storage: ArtworkStorage | None = None,
) -> ArtworkGenerationOutput:
    """Generate finalist variants, persist binaries, and retain references for review."""

    storage_adapter = storage or ReferenceArtworkStorage()
    jobs = [
        (index, prompt, variant_number)
        for index, prompt in enumerate(input_data.prompts)
        for variant_number in range(1, input_data.artwork_variants_per_concept + 1)
    ]

    def _generate_one(job: tuple[int, PromptCompilation, int]):
        index, prompt, variant_number = job
        generated = provider.generate(
            ImageGenerationRequest(
                concept_id=prompt.concept_id,
                brief_id=prompt.brief_id,
                prompt=prompt.prompt,
                variant_number=variant_number,
            )
        )
        stored = storage_adapter.persist(
            source_url=generated.source_url,
            storage_key=generated.storage_key,
            reported_size_bytes=generated.file_size_bytes,
            content=generated.content,
        )
        artwork = Artwork(
            run_id=prompt.run_id,
            concept_id=prompt.concept_id,
            brief_id=prompt.brief_id,
            prompt=prompt.prompt,
            combination_name=prompt.combination_name,
            storage_key=stored.storage_key,
            critique=_artwork_critique(prompt),
            raw_storage_key=stored.raw_storage_key,
            source_url=generated.source_url,
            width=stored.width or generated.width,
            height=stored.height or generated.height,
            mime_type=stored.mime_type or generated.mime_type,
            file_size_bytes=stored.file_size_bytes,
        )
        return index, artwork, generated.usage

    if not jobs:
        return ArtworkGenerationOutput()
    workers = min(8, len(jobs))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        finished = list(pool.map(_generate_one, jobs))
    finished.sort(key=lambda item: item[0])
    artworks = [item[1] for item in finished]
    usages = [item[2] for item in finished]
    return ArtworkGenerationOutput(artworks=artworks, usage=combine_usage(*usages))
