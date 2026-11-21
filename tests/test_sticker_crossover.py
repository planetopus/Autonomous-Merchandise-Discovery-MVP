"""Niche A + niche B flows through research, copy, and artwork prompts."""

from unittest.mock import Mock

from merchandise_discovery.application.discovery_stage_executor import DiscoveryStageExecutor
from merchandise_discovery.domain.models.common import IdentityType, PipelineVariant, SocialSource
from merchandise_discovery.domain.models.workflow import RunConfig, StageExecution, WorkflowRun
from merchandise_discovery.domain.pipelines.social_behavior_text import artwork, pipeline
from merchandise_discovery.domain.pipelines.social_identity_v2 import pipeline as identity_v2


def test_crossover_is_included_in_research_and_artwork_prompts() -> None:
    """A completed pair changes the search request and the Grok wrapper."""

    behavior_input = pipeline.SocialBehaviorTextInput(
        sources=[SocialSource.REDDIT],
        query="sharing a couch with a working dog",
        candidate_count=1,
        niche_a="night-shift nurses",
        niche_b="pit bull owners",
    )
    user_prompt = pipeline.build_user_prompt(behavior_input)
    assert 'both "night-shift nurses" and "pit bull owners"' in user_prompt
    assert "4 to 14 words" in user_prompt

    candidate = pipeline.execute(behavior_input).candidates[0]
    image_prompt = artwork.build_targeted_artwork_prompt(
        candidate,
        niche_a="night-shift nurses",
        niche_b="pit bull owners",
    )
    assert "die-cut vinyl sticker" in image_prompt
    assert 'both "night-shift nurses" and "pit bull owners"' in image_prompt
    assert "scene or landscape background" in image_prompt
    assert "full-bleed background" in image_prompt

    blank = pipeline.build_user_prompt(
        pipeline.SocialBehaviorTextInput(
            sources=[SocialSource.REDDIT],
            query="sharing a couch with a working dog",
            candidate_count=1,
        )
    )
    assert "Crossover niches" not in blank


def test_identity_prompt_keeps_working_and_accepts_a_crossover() -> None:
    """Existing single-identity runs stay valid, and a pair is added when supplied."""

    solo = identity_v2.SocialIdentityV2Input(
        sources=[SocialSource.REDDIT],
        identity="bedside nurses",
        identity_type=IdentityType.OCCUPATION,
        query="charting after a shift",
        candidate_count=1,
    )
    solo_prompt = identity_v2.build_user_prompt(solo)
    assert "bedside nurses" in solo_prompt
    assert "Crossover niches" not in solo_prompt
    assert "4 to 14 words" in solo_prompt

    crossed = solo.model_copy(update={"niche_a": "bedside nurses", "niche_b": "houseplant people"})
    crossed_prompt = identity_v2.build_user_prompt(crossed)
    assert 'both "bedside nurses" and "houseplant people"' in crossed_prompt


def test_executor_passes_the_niche_pair_into_both_social_stages() -> None:
    """Stage 1 research and Stage 2 artwork both receive the same crossover."""

    run = WorkflowRun(
        title="Crossover",
        config=RunConfig(
            pipeline_variant=PipelineVariant.SOCIAL_BEHAVIOR_TEXT,
            social_sources=[SocialSource.REDDIT],
            social_query="sharing a couch with a working dog",
            social_candidate_count=1,
            social_niche_a="night-shift nurses",
            social_niche_b="pit bull owners",
        ),
    )
    stage_repository = Mock()
    executor = DiscoveryStageExecutor(
        *(Mock() for _ in range(2)),
        stage_repository,
        *(Mock() for _ in range(7)),
    )
    stage_one = StageExecution(
        run_id=run.run_id,
        stage_number=1,
        stage_name="Social Behavior to Merchandise Text",
    )
    prepared = executor.prepare(run, stage_one)
    assert prepared["niche_a"] == "night-shift nurses"
    assert prepared["niche_b"] == "pit bull owners"

    stage_repository.get_latest.return_value = StageExecution(
        run_id=run.run_id,
        stage_number=1,
        stage_name="Social Behavior to Merchandise Text",
        output_data=pipeline.execute(
            pipeline.SocialBehaviorTextInput.model_validate(prepared)
        ).model_dump(mode="python"),
    )
    stage_two = StageExecution(
        run_id=run.run_id,
        stage_number=2,
        stage_name="Social Merchandise Artwork Generation",
    )
    artwork_input = executor.prepare(run, stage_two)
    assert artwork_input["niche_a"] == "night-shift nurses"
    assert artwork_input["niche_b"] == "pit bull owners"
