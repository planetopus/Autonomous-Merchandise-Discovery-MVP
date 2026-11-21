"""Finished stickers are original puns with one generated image each."""

from types import SimpleNamespace

from merchandise_discovery.application.stage_runner import stop_after_for_run
from merchandise_discovery.domain.humor import is_anchor_echo, puns_still_needed
from merchandise_discovery.domain.models.common import PipelineVariant, SocialSource
from merchandise_discovery.domain.models.workflow import RunConfig, WorkflowRun
from merchandise_discovery.domain.pipelines.social_behavior_text.artwork import (
    build_targeted_artwork_prompt,
)
from merchandise_discovery.domain.pipelines.social_behavior_text.pipeline import (
    SocialBehaviorTextCandidate,
)
from merchandise_discovery.infrastructure.providers.image_provider import (
    estimate_image_cost,
    image_backend_name,
)


def test_xai_is_the_default_image_provider_when_its_key_is_set() -> None:
    """OpenAI images run only when MVP_IMAGE_PROVIDER=openai. Five xAI images are about $0.10."""

    assert image_backend_name("sk-openai", "sk-xai", live=True) == "xAI grok-imagine-image"
    assert (
        image_backend_name("sk-openai", "sk-xai", live=True, prefer="openai")
        == "openai gpt-image-1"
    )
    assert image_backend_name("", "sk-xai", live=True, xai_model="grok-imagine-image") == (
        "xAI grok-imagine-image"
    )
    assert image_backend_name("sk-openai", "", live=True) == "openai gpt-image-1"
    assert image_backend_name("sk-openai", "sk-xai", live=False) == "fixture"
    assert estimate_image_cost("openai gpt-image-1", 5) == 0.20
    assert estimate_image_cost("xAI grok-imagine-image", 5) == 0.10
    assert estimate_image_cost("fixture", 5) == 0.0


def test_text_plus_images_reaches_stage_2_when_the_env_stop_is_1() -> None:
    """The checkbox, not only MVP_STOP_AFTER_STAGE, decides whether images run."""

    social = WorkflowRun(
        title="Stickers",
        config=RunConfig(
            pipeline_variant=PipelineVariant.SOCIAL_IDENTITY_V2,
            social_generate_images=True,
        ),
    )
    text_only = social.model_copy(
        update={"config": social.config.model_copy(update={"social_generate_images": False})}
    )
    baseline = WorkflowRun(title="Funnel", config=RunConfig())

    assert stop_after_for_run(social, 1) == 2
    assert stop_after_for_run(text_only, 1) == 1
    assert stop_after_for_run(baseline, 1) == 1


def test_anchor_lines_are_blocked_and_a_batch_of_five_needs_three_puns() -> None:
    """The anchors are style, not lines to ship. Five finals need three puns."""

    assert is_anchor_echo("NACHO AVERAGE NURSE")
    assert is_anchor_echo("nacho average nurse")
    assert not is_anchor_echo("NACHO AVERAGE NIGHT SHIFT")
    assert puns_still_needed(5, 2) == 1
    assert puns_still_needed(5, 3) == 0
    assert puns_still_needed(2, 0) == 0


def test_the_image_prompt_asks_for_the_exact_line_and_a_thick_white_outline() -> None:
    """Stage 2 tells the image model to finish the sticker, not illustrate a scene."""

    candidate = SocialBehaviorTextCandidate(
        source_platform=SocialSource.REDDIT,
        source_url="https://reddit.com/r/nursing/comments/abc/nachos",
        source_title="Shift snack",
        source_excerpt="Nurses eat chips at the desk.",
        audience_context="Nurses on a night shift.",
        behavior="Eating at the desk.",
        friction_or_pressure="The shift runs long.",
        artwork_text="NACHO AVERAGE NURSE",
        image_idea="A cute tortilla chip in blue scrubs with a stethoscope.",
        why_it_works="The chip is the nacho and the scrubs are the nurse.",
        format="bold text stack",
        artwork_prompt="A die-cut sticker of one chip character.",
        visual_punchline="The chip wears scrubs.",
        main_visual_metaphor="A chip in scrubs.",
        audience_specific_cue="Scrubs and a stethoscope.",
        tone="deadpan",
        style_direction="Flat vector sticker.",
        things_to_avoid=["a scene"],
        specificity_reason="The scrubs make the pun.",
        who_its_for=["nurses", "night shift"],
    )
    prompt = build_targeted_artwork_prompt(candidate)

    assert "NACHO AVERAGE NURSE" in prompt
    assert "thick white outline" in prompt
    assert "die-cut vinyl sticker" in prompt.casefold()
    assert "tortilla chip" in prompt.casefold()
    line = SimpleNamespace(pattern="name_swap", humor_mechanism="")
    from merchandise_discovery.domain.humor import line_is_pun

    assert line_is_pun(line)
