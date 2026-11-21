"""Tests for the one-stage social behavior to text pipeline."""

from unittest.mock import Mock

from merchandise_discovery.application.discovery_stage_executor import DiscoveryStageExecutor
from merchandise_discovery.domain.models.common import PipelineVariant, SocialSource
from merchandise_discovery.domain.models.usage import UsageMetrics
from merchandise_discovery.domain.models.workflow import RunConfig, StageExecution, WorkflowRun
from merchandise_discovery.domain.pipelines.social_behavior_text import pipeline
from merchandise_discovery.domain.stages.registry import stage_definitions_for
from merchandise_discovery.infrastructure.providers.image_provider import FixtureImageProvider
from tests.live_reasoning import first_writer_call, scripted_social_provider


def _executor(stage_repository: Mock) -> DiscoveryStageExecutor:
    """Construct the executor with repository doubles; the social stage needs none of them."""

    return DiscoveryStageExecutor(
        *(Mock() for _ in range(2)),
        stage_repository,
        *(Mock() for _ in range(7)),
    )


def test_social_behavior_pipeline_has_text_and_artwork_stages() -> None:
    """The social pipeline has one reasoning stage followed by one Grok generation stage."""

    definitions = stage_definitions_for(PipelineVariant.SOCIAL_BEHAVIOR_TEXT)

    assert [(definition.number, definition.name) for definition in definitions] == [
        (1, "Social Behavior to Merchandise Text"),
        (2, "Social Merchandise Artwork Generation"),
    ]


def test_social_behavior_pipeline_fixture_returns_text_candidates() -> None:
    """Fixture mode keeps the new UI demonstrable without pretending a social search occurred."""

    run = WorkflowRun(
        title="Social behavior fixture",
        config=RunConfig(
            pipeline_variant=PipelineVariant.SOCIAL_BEHAVIOR_TEXT,
            social_sources=[SocialSource.REDDIT],
            social_query="people optimizing sleep after doom-scrolling",
            social_candidate_count=2,
        ),
    )
    stage = StageExecution(
        run_id=run.run_id,
        stage_number=1,
        stage_name="Social Behavior to Merchandise Text",
    )
    executor = _executor(Mock())

    input_data = executor.prepare(run, stage)
    result = executor.execute(run, stage, input_data)

    assert len(result.output_data["candidates"]) == 2
    assert result.output_data["model"] == "deterministic"
    assert result.output_data["candidates"][0]["source_platform"] == SocialSource.REDDIT.value
    assert result.output_data["candidates"][0]["artwork_prompt"]


def test_social_behavior_pipeline_can_delegate_topic_selection_to_ai() -> None:
    """Auto-topic mode accepts no manual query and explicitly instructs the provider to choose."""

    input_model = pipeline.SocialBehaviorTextInput(
        sources=[SocialSource.REDDIT],
        auto_topic=True,
        candidate_count=1,
    )

    prompt = pipeline.build_user_prompt(input_model)
    fixture_output = pipeline.execute(input_model)

    assert "Choose the behavior or topic yourself" in prompt
    assert "topic_explored" in prompt
    assert fixture_output.topic_explored
    assert fixture_output.candidates[0].artwork_text != "Still doing "


def test_social_stage_two_uses_stage_one_prompt_and_shared_image_contract() -> None:
    """Stage 2 consumes the persisted prompt and stores provider-neutral artwork metadata."""

    run = WorkflowRun(
        title="Social artwork fixture",
        config=RunConfig(
            pipeline_variant=PipelineVariant.SOCIAL_BEHAVIOR_TEXT,
            social_sources=[SocialSource.REDDIT],
            social_query="people optimizing sleep after doom-scrolling",
            social_candidate_count=1,
        ),
    )
    stage_repository = Mock()
    stage_one = StageExecution(
        run_id=run.run_id,
        stage_number=1,
        stage_name="Social Behavior to Merchandise Text",
        output_data=pipeline.execute(
            pipeline.SocialBehaviorTextInput(
                sources=[SocialSource.REDDIT],
                query=run.config.social_query,
                candidate_count=1,
            )
        ).model_dump(mode="python"),
    )
    stage_repository.get_latest.return_value = stage_one
    executor = _executor(stage_repository)
    executor._image_provider = FixtureImageProvider()

    stage_two = StageExecution(
        run_id=run.run_id,
        stage_number=2,
        stage_name="Social Merchandise Artwork Generation",
    )
    input_data = executor.prepare(run, stage_two)
    result = executor.execute(run, stage_two, input_data)

    assert len(result.output_data["artworks"]) == 1
    generated_prompt = result.output_data["artworks"][0]["prompt"]
    assert input_data["candidates"][0]["artwork_prompt"] in generated_prompt
    assert "die-cut vinyl sticker" in generated_prompt
    assert "plain white background" in generated_prompt
    assert "realistic shading" in generated_prompt
    assert "poster layout" in generated_prompt
    assert "soft lifestyle photography" in generated_prompt
    assert result.output_data["artworks"][0]["source_url"].startswith("https://fixture.local/")


def test_social_behavior_pipeline_passes_live_source_scope_to_provider() -> None:
    """Live execution makes one structured request constrained to the selected social domains."""

    run = WorkflowRun(
        title="Social behavior live",
        config=RunConfig(
            pipeline_variant=PipelineVariant.SOCIAL_BEHAVIOR_TEXT,
            social_sources=[SocialSource.REDDIT, SocialSource.X],
            social_query="night workers trying to stay sane",
            social_candidate_count=1,
        ),
    )
    stage = StageExecution(
        run_id=run.run_id,
        stage_number=1,
        stage_name="Social Behavior to Merchandise Text",
    )
    candidate = pipeline.SocialBehaviorTextCandidate(
        source_platform=SocialSource.REDDIT,
        source_url="https://reddit.com/r/example/comments/abc/example",
        source_title="Example discussion",
        source_excerpt="A source-backed behavior.",
        audience_context="Night workers",
        behavior="Trying to decompress after a shift.",
        friction_or_pressure="The next shift starts too soon.",
        artwork_text="My sleep schedule is a group project",
        artwork_prompt=(
            'Text-first shirt design. Render the exact line "My sleep schedule is a group project" '
            "with a specific night-shift visual metaphor."
        ),
        visual_punchline="Sleep becomes a group project that refuses to end on time.",
        main_visual_metaphor="A night-shift clock is trapped in a chaotic project meeting.",
        audience_specific_cue="Night workers trying to sleep before the next shift.",
        tone="dry and self-aware",
        style_direction="Bold limited-palette screen-print illustration.",
        things_to_avoid=["generic clock art", "soft bedroom scene", "extra text"],
        specificity_reason="The line reflects a recognizable shift-work tension.",
    )
    provider = scripted_social_provider(
        pipeline.SocialBehaviorTextOutput(
            candidates=[candidate],
            search_summary="One source-backed behavior.",
        ),
        UsageMetrics(provider="openai", model="gpt-4o-mini", request_count=1),
    )
    executor = _executor(Mock())
    executor._reasoning_provider = provider

    input_data = executor.prepare(run, stage)
    result = executor.execute(run, stage, input_data)

    call = first_writer_call(provider).kwargs
    assert call["web_search_domains"] == ("reddit.com", "x.com")
    assert result.output_data["candidates"][0]["artwork_text"] == (
        "My sleep schedule is a group project"
    )
    assert result.output_data["candidates"][0]["artwork_prompt"]


def test_social_behavior_prompt_requires_standalone_personal_copy() -> None:
    """The product line must carry enough context without relying on hidden metadata."""

    instructions = pipeline.reasoning_instructions()

    assert "MUST make sense when read alone" in instructions
    assert "Preserve the personal relationship" in instructions
    assert "4 to 14 words" in instructions
    assert "pun alone is rejected" in instructions
    assert "artwork_text may be an empty string" in instructions
    assert "die-cut vinyl sticker" in instructions
    assert "plain white background" in instructions
    assert "realistic shading" in instructions
    assert "poster layout" in instructions
    assert "Avoid generic achievement statements" in instructions
    assert "artwork_prompt" in instructions
    assert "exact merchandise line" in instructions
    blank_prompt = pipeline.build_user_prompt(
        pipeline.SocialBehaviorTextInput(
            sources=[SocialSource.REDDIT],
            query="night workers trying to stay sane",
            candidate_count=1,
        )
    )
    assert "visual_punchline" in blank_prompt
    assert "two different niches" in blank_prompt
    assert "original joke" in blank_prompt


def test_reddit_403_still_asks_web_search_for_source_evidence() -> None:
    """A blocked comment fetch does not fail stage 1 or drop the source-quote requirement."""

    run = WorkflowRun(
        title="Reddit blocked",
        config=RunConfig(
            pipeline_variant=PipelineVariant.SOCIAL_BEHAVIOR_TEXT,
            social_sources=[SocialSource.REDDIT],
            social_query="night shift charting",
            social_candidate_count=1,
            social_niche_a="night-shift nurses",
            social_niche_b="true crime",
        ),
    )
    stage = StageExecution(run_id=run.run_id, stage_number=1, stage_name="Social text")
    candidate = pipeline.SocialBehaviorTextCandidate(
        source_platform=SocialSource.REDDIT,
        source_url="https://reddit.com/r/nursing/comments/abc/chart",
        source_title="Charting",
        source_excerpt="A nurse describes finishing notes in the car.",
        source_quote="I finish the note in the parking lot.",
        audience_context="Nurses who listen to cases on the way home.",
        behavior="Finishing the chart after clock-out.",
        friction_or_pressure="The story is not done when the shift is.",
        artwork_text="My parking lot is the second desk",
        artwork_prompt="A die-cut sticker of a badge on a steering wheel.",
        visual_punchline="The badge is driving.",
        main_visual_metaphor="A badge gripping a steering wheel.",
        audience_specific_cue="A nurse badge and a steering wheel.",
        tone="deadpan",
        style_direction="Flat vector die-cut sticker.",
        things_to_avoid=["a scene"],
        specificity_reason="Both lives are in the line.",
        pattern="confession",
    )
    provider = scripted_social_provider(
        pipeline.SocialBehaviorTextOutput(
            candidates=[candidate],
            search_summary="Search excerpts covered the parking-lot notes.",
        )
    )

    class BlockedReddit:
        def collect(self, query: str) -> list:
            raise RuntimeError("Reddit request failed with status 403.")

    executor = _executor(Mock())
    executor._reasoning_provider = provider
    executor._reddit_reader = BlockedReddit()

    result = executor.execute(run, stage, executor.prepare(run, stage))

    prompt = first_writer_call(provider).kwargs["user_prompt"]
    assert "No comments were prefetched" in prompt
    assert first_writer_call(provider).kwargs["web_search_domains"] == ("reddit.com",)
    assert result.output_data["candidates"][0]["source_quote"]


def test_live_stage_drops_source_quotes_and_always_runs_the_critic() -> None:
    """A blank reference set still scores every line and rejects a copied source sentence."""

    run = WorkflowRun(
        title="Source copy",
        config=RunConfig(
            pipeline_variant=PipelineVariant.SOCIAL_BEHAVIOR_TEXT,
            social_sources=[SocialSource.REDDIT],
            social_query="first layer problems",
            social_candidate_count=1,
            social_niche_a="night-shift nurses",
            social_niche_b="3D printer people",
        ),
    )
    stage = StageExecution(run_id=run.run_id, stage_number=1, stage_name="Social text")
    copied = "This is with a 0.4 mm nozzle."
    joke = pipeline.SocialBehaviorTextCandidate(
        source_platform=SocialSource.REDDIT,
        source_url="https://reddit.com/r/3Dprinting/comments/abc/nozzle",
        source_title="Nozzle note",
        source_excerpt=copied,
        source_quote=copied,
        audience_context="Nurses who also print",
        behavior="Blaming the nozzle for a shift-change print.",
        friction_or_pressure="The print fails at the same minute the shift ends.",
        artwork_text="My first layer clocks out early",
        artwork_prompt="A die-cut sticker of a nozzle punching a time clock.",
        visual_punchline="The nozzle leaves mid-layer.",
        main_visual_metaphor="A nozzle wearing a nurse's badge clocking out.",
        audience_specific_cue="A badge and a 0.4 mm nozzle on one subject.",
        tone="deadpan",
        style_direction="Flat vector die-cut sticker.",
        things_to_avoid=["a scene"],
        specificity_reason="Both lives are in the line.",
        humor_mechanism="deadpan absurd",
        concrete_detail="0.4 mm nozzle",
    )
    quoted = joke.model_copy(update={"artwork_text": copied})
    provider = scripted_social_provider(
        pipeline.SocialBehaviorTextOutput(
            candidates=[quoted, joke],
            search_summary="Printer comments from people who also work nights.",
            niche_pair_a="night-shift nurses",
            niche_pair_b="3D printer people",
            pairing_score=8,
            pairing_reason="The same person prints between shifts.",
        )
    )
    executor = _executor(Mock())
    executor._reasoning_provider = provider

    result = executor.execute(run, stage, executor.prepare(run, stage))

    assert result.output_data["candidates"][0]["artwork_text"] == "My first layer clocks out early"
    assert result.output_data["candidates"][0]["funny_score"] == 8
    assert result.output_data["niche_pair_a"] == "night-shift nurses"
    assert result.output_data["niche_pair_b"] == "3D printer people"
    reasons = {item["reason"] for item in result.output_data["line_reviews"]}
    assert "copied source" in reasons
    assert "kept" in reasons
    assert any(
        call.kwargs["response_model"].__name__ == "HumorCritiqueBatch"
        for call in provider.complete_structured.call_args_list
    )


def test_missing_identity_stacks_do_not_fail_the_run() -> None:
    """A short stack quota keeps the niche pair, every draft, and the token total."""

    from types import SimpleNamespace

    from merchandise_discovery.domain.humor import HumorCritiqueBatch, HumorCritiqueItem
    from merchandise_discovery.domain.models.usage import UsageMetrics

    run = WorkflowRun(
        title="Short stacks",
        config=RunConfig(
            pipeline_variant=PipelineVariant.SOCIAL_BEHAVIOR_TEXT,
            social_sources=[SocialSource.REDDIT],
            social_query="shift podcasts",
            social_candidate_count=2,
            social_niche_a="night-shift nurses",
            social_niche_b="true crime",
        ),
    )
    stage = StageExecution(run_id=run.run_id, stage_number=1, stage_name="Social text")
    base = pipeline.SocialBehaviorTextCandidate(
        source_platform=SocialSource.REDDIT,
        source_url="https://reddit.com/r/nursing/comments/abc/podcast",
        source_title="Night podcast",
        source_excerpt="Nurses talk through a case while a podcast plays.",
        audience_context="Nurses who listen to cases on the drive home.",
        behavior="Replaying a shift out loud.",
        friction_or_pressure="The story is not over when the shift is.",
        artwork_text="My commute files a second chart",
        artwork_prompt="A die-cut sticker of a badge and headphones as one subject.",
        visual_punchline="The badge is wearing headphones.",
        main_visual_metaphor="A badge with headphones.",
        audience_specific_cue="A nurse badge and a headphone cord.",
        tone="deadpan",
        style_direction="Flat vector die-cut sticker.",
        things_to_avoid=["a scene"],
        specificity_reason="Both lives are in the line.",
        pattern="confession",
    )
    measured = UsageMetrics(
        provider="openai",
        model="gpt-5",
        request_count=1,
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        estimated_cost_usd=0.01,
        cost_is_estimate=True,
    )
    provider = Mock()

    def respond(**kwargs):
        name = kwargs["response_model"].__name__
        if name == "HumorCritiqueBatch":
            return SimpleNamespace(
                output=HumorCritiqueBatch(
                    reviews=[
                        HumorCritiqueItem(
                            index=index,
                            humor_landed=8,
                            novelty=8,
                            tone_match=8,
                            giftability=6,
                            reddit_upvote_score=8,
                            sticker_buy_score=8,
                        )
                        for index in range(4)
                    ]
                ),
                usage=measured,
            )
        return SimpleNamespace(
            output=pipeline.SocialBehaviorTextOutput(
                candidates=[base],
                search_summary="One confession and no stacked club name.",
                niche_pair_a="night-shift nurses",
                niche_pair_b="true crime",
                pairing_score=9,
            ),
            usage=measured,
        )

    provider.complete_structured.side_effect = respond
    executor = _executor(Mock())
    executor._reasoning_provider = provider

    result = executor.execute(run, stage, executor.prepare(run, stage))

    assert result.output_data["niche_pair_a"] == "night-shift nurses"
    assert result.output_data["niche_pair_b"] == "true crime"
    assert result.output_data["candidates"]
    assert result.output_data["line_reviews"]
    assert "absurd identity stack" in result.output_data["stage_warning"].casefold()
    assert result.usage.total_tokens > 0
    assert result.usage.request_count >= 2
    # Draft, critic, one stack refill, and one critic for that refill. No second full rewrite.
    assert provider.complete_structured.call_count == 4
    assert all(
        call.kwargs.get("reasoning_effort") == "low"
        for call in provider.complete_structured.call_args_list
    )


def test_live_run_returns_two_absurd_identity_stacks() -> None:
    """A run that asks for more than one line keeps two stacked-club jokes from its niches."""

    run = WorkflowRun(
        title="Stacks",
        config=RunConfig(
            pipeline_variant=PipelineVariant.SOCIAL_BEHAVIOR_TEXT,
            social_sources=[SocialSource.REDDIT],
            social_query="shift podcasts",
            social_candidate_count=2,
            social_niche_a="night-shift nurses",
            social_niche_b="true crime",
        ),
    )
    stage = StageExecution(run_id=run.run_id, stage_number=1, stage_name="Social text")
    base = pipeline.SocialBehaviorTextCandidate(
        source_platform=SocialSource.REDDIT,
        source_url="https://reddit.com/r/nursing/comments/abc/podcast",
        source_title="Night podcast",
        source_excerpt="Nurses talk through a case while a podcast plays.",
        audience_context="Nurses who listen to cases on the drive home.",
        behavior="Replaying a shift out loud.",
        friction_or_pressure="The story is not over when the shift is.",
        artwork_text="My commute files a second chart",
        artwork_prompt="A die-cut sticker of a badge and headphones as one subject.",
        visual_punchline="The badge is wearing headphones.",
        main_visual_metaphor="A badge with headphones.",
        audience_specific_cue="A nurse badge and a headphone cord.",
        tone="deadpan",
        style_direction="Flat vector die-cut sticker.",
        things_to_avoid=["a scene"],
        specificity_reason="Both lives are in the line.",
        pattern="confession",
    )
    stacks = [
        base.model_copy(
            update={
                "artwork_text": "NIGHT SHIFT TRUE CRIME CLUB",
                "pattern": "absurd_identity_stack",
            }
        ),
        base.model_copy(
            update={
                "artwork_text": "CHARTING AND CHILL PODCAST",
                "pattern": "ABSURD IDENTITY STACK",
                "source_url": "https://reddit.com/r/nursing/comments/abc/club",
            }
        ),
    ]
    provider = scripted_social_provider(
        pipeline.SocialBehaviorTextOutput(
            candidates=[base, *stacks],
            search_summary="Nurses and true-crime listeners overlap on the drive home.",
        )
    )
    executor = _executor(Mock())
    executor._reasoning_provider = provider

    result = executor.execute(run, stage, executor.prepare(run, stage))

    returned = result.output_data["candidates"]
    assert len(returned) == 2
    assert all(
        "absurd identity stack" in item["pattern"].casefold().replace("_", " ")
        for item in returned
    )
    assert any(item["id"] == "absurd_identity_stack" for item in result.output_data["humor_playbook_used"])
