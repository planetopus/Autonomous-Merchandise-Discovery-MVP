"""The humor lab is optional. Present files change the prompt, the bank, and the critic."""

from types import SimpleNamespace
from unittest.mock import Mock

from merchandise_discovery.application.discovery_stage_executor import DiscoveryStageExecutor
from merchandise_discovery.domain.humor_playbook import build_playbook
from merchandise_discovery.domain.models.common import PipelineVariant, SocialSource
from merchandise_discovery.domain.models.workflow import RunConfig, StageExecution, WorkflowRun
from merchandise_discovery.domain.pipelines.social_behavior_text import pipeline
from merchandise_discovery.infrastructure.humor_lab_loader import (
    load_humor_lab,
    merge_lab_playbook,
)
from tests.live_reasoning import scripted_social_provider


def test_missing_humor_lab_is_empty(tmp_path) -> None:
    """A directory without the lab files does not invent pairs or gold lines."""

    lab = load_humor_lab(tmp_path)

    assert lab.playbook is None
    assert lab.niche_pairs == []
    assert lab.gold_lines == []
    assert lab.rubric == ""


def test_lab_files_load_and_override_a_matching_pattern(tmp_path) -> None:
    """playbook.json, niche pairs, gold lines, and the rubric are all optional files."""

    folder = tmp_path / "humor_lab"
    folder.mkdir()
    (folder / "playbook.json").write_text(
        '{"patterns":[{"id":"absurd_identity_stack","label":"Absurd identity stack",'
        '"guidance":"Name a real co-occurring group in a younger register.","priority":true}]}',
        encoding="utf-8",
    )
    (folder / "niche_pairs.json").write_text(
        '{"pairs":[{"niche_a":"church dads","niche_b":"weekend grilling"}]}',
        encoding="utf-8",
    )
    (folder / "gold_lines.json").write_text(
        '{"lines":[{"text":"the lab example line stays off the sticker"}]}',
        encoding="utf-8",
    )
    (folder / "critic_rubric.md").write_text(
        "LAB RUBRIC: a member must say that's me and buy it.",
        encoding="utf-8",
    )

    lab = load_humor_lab(folder)
    merged = merge_lab_playbook(build_playbook([]), lab.playbook)

    assert lab.niche_pairs == [{"niche_a": "church dads", "niche_b": "weekend grilling"}]
    assert lab.gold_lines == ["the lab example line stays off the sticker"]
    assert "LAB RUBRIC" in lab.rubric
    stack = next(item for item in merged["patterns"] if item["id"] == "absurd_identity_stack")
    assert "younger register" in stack["guidance"]


def test_live_run_uses_the_lab_bank_gold_lines_and_rubric(monkeypatch) -> None:
    """When the lab is present, pairs, style lines, and the rubric reach the model."""

    from merchandise_discovery.infrastructure.humor_lab_loader import HumorLab

    lab = HumorLab(
        playbook=None,
        niche_pairs=[{"niche_a": "church dads", "niche_b": "weekend grilling"}],
        gold_lines=["the lab example line stays off the sticker"],
        rubric="LAB RUBRIC: a member must say that's me and buy it.",
    )
    monkeypatch.setattr(
        "merchandise_discovery.application.discovery_stage_executor.load_humor_lab",
        lambda: lab,
    )
    run = WorkflowRun(
        title="Lab",
        config=RunConfig(
            pipeline_variant=PipelineVariant.SOCIAL_BEHAVIOR_TEXT,
            social_sources=[SocialSource.REDDIT],
            social_query="weekend plans",
            social_candidate_count=1,
        ),
    )
    stage = StageExecution(run_id=run.run_id, stage_number=1, stage_name="Social text")
    candidate = pipeline.execute(
        pipeline.SocialBehaviorTextInput(
            sources=[SocialSource.REDDIT],
            query="weekend plans",
            candidate_count=1,
        )
    ).candidates[0].model_copy(
        update={
            "source_url": "https://reddit.com/r/daddit/comments/abc/grill",
            "artwork_text": "My weekend shift is the grill",
            "pattern": "confession",
        }
    )
    provider = scripted_social_provider(
        pipeline.SocialBehaviorTextOutput(
            candidates=[candidate],
            search_summary="Dads who grill on the weekend.",
        )
    )
    executor = DiscoveryStageExecutor(*(Mock() for _ in range(10)))
    executor._reasoning_provider = provider

    executor.execute(run, stage, executor.prepare(run, stage))

    prompts = [call.kwargs.get("user_prompt", "") for call in provider.complete_structured.call_args_list]
    systems = [call.kwargs.get("system_prompt", "") for call in provider.complete_structured.call_args_list]
    assert any("broad appeal" in prompt.casefold() for prompt in prompts)
    assert not any("weekend grilling" in prompt.casefold() for prompt in prompts)
    assert any("the lab example line stays off the sticker" in prompt for prompt in prompts)
    assert any("Never output these lines" in prompt for prompt in prompts)
    assert any("LAB RUBRIC" in prompt for prompt in systems)


def test_a_copied_gold_line_is_dropped() -> None:
    """A merchandise line that repeats a lab example does not survive."""

    from merchandise_discovery.application.discovery_stage_executor import DiscoveryStageExecutor

    executor = DiscoveryStageExecutor(*(Mock() for _ in range(10)))
    candidate = SimpleNamespace(
        artwork_text="the lab example line stays off the sticker",
        pattern="confession",
        source_quote="something else entirely",
        source_excerpt="unrelated excerpt",
    )
    kept, dropped = executor._drop_unoriginal(
        [candidate],
        [],
        ["the lab example line stays off the sticker"],
    )

    assert kept == []
    assert dropped[0].reason == "copied gold line"
