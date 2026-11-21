"""Stage 14: compile deterministic, policy-complete prompts from design briefs."""

from pydantic import BaseModel

from merchandise_discovery.domain.models.artifacts import DesignBrief


class PromptCompilation(BaseModel):
    """One compiled prompt linked to the brief and concept that produced it."""

    run_id: str
    concept_id: str
    brief_id: str
    prompt: str
    combination_name: str = ""
    audience_label: str = ""


class PromptCompilationInput(BaseModel):
    """Design briefs awaiting deterministic prompt compilation."""

    briefs: list[DesignBrief]


class PromptCompilationOutput(BaseModel):
    """Compiled prompts passed to the image-generation stage."""

    prompts: list[PromptCompilation]
    summary: str = ""


def _compile(brief: DesignBrief) -> str:
    """Apply brief-specific instructions plus permanent merchandise safety/layout rules."""

    constraints = "; ".join(brief.constraints + brief.things_to_avoid)
    phrase = brief.exact_phrase.strip()
    text_rule = (
        "Merchandise text: none. Do not render any words, letters, or captions. "
        if not phrase
        else (
            f'Exact text: "{phrase}" (primary audience-recognition copy). '
            "Render the exact text prominently while preserving its original audience voice; do not "
            "convert it into a product category, club name, campaign title, or generic theme. "
        )
    )
    return (
        "Create a die-cut vinyl sticker, not a T-shirt graphic, poster, or product mockup. "
        "Use flat vector-style illustration, bold clean outlines, flat colors, and one centered "
        "isolated subject on a plain white background. Do not use a scene, landscape, full-bleed "
        "background, realistic shading, semi-realistic comic shading, or a poster layout. "
        "Use a square 1:1 aspect ratio unless the brief explicitly requests another ratio. "
        f"{text_rule}"
        f"Target audience: {brief.target_audience}. "
        f"Mandatory audience recognition cues that must be visibly represented: "
        f"{', '.join(brief.audience_visual_cues)}. "
        f"Core concept: {brief.core_concept}. "
        f"Emotional idea: {brief.emotional_idea}. "
        f"Main subject: {brief.main_subject}. "
        f"Supporting elements: {', '.join(brief.supporting_elements)}. "
        f"Style: {brief.illustration_style}. "
        f"Composition: {brief.composition}. "
        f"Typography: {brief.typography_direction}. "
        f"Palette: {brief.palette_direction}. "
        f"Detail level: {brief.detail_level}. "
        "Intended merchandise: die-cut vinyl sticker. "
        f"Visual constraints and avoid list: {constraints}. "
        "Audience identity must be recognizable from the phrase and mandatory cues together, not "
        "from generic props alone. "
        "Permanent rules: no extra text, no logos or brand marks, no product mockup, no scene or "
        "landscape, no full-bleed background, no realistic shading, no poster layout, plain white "
        "background, one centered subject, preserve exact spelling, and keep the design legible "
        "at sticker scale. Do not draw the white die-cut border; it is added after generation."
    )


def execute(input_data: PromptCompilationInput) -> PromptCompilationOutput:
    """Compile one reproducible prompt for each finalist brief."""

    return PromptCompilationOutput(
        prompts=[
            PromptCompilation(
                run_id=brief.run_id,
                concept_id=brief.concept_id,
                brief_id=brief.brief_id,
                prompt=_compile(brief),
                combination_name=brief.combination_name,
            )
            for brief in input_data.briefs
        ],
        summary="Compiled prompts with deterministic brief and permanent merchandise rules.",
    )
