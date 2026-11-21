"""The humor lab is optional. Present files change the prompt, the bank, and the critic."""

from types import SimpleNamespace
from unittest.mock import Mock

from merchandise_discovery.application.discovery_stage_executor import DiscoveryStageExecutor
from merchandise_discovery.domain.humor import (
    LineReview,
    apply_line_critic,
    apply_trope_cap,
    stacked_trait_count,
)
from merchandise_discovery.domain.humor_playbook import build_playbook
from merchandise_discovery.domain.models.common import HumorTone, PipelineVariant, SocialSource
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
    assert lab.tired_tropes == []


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


def test_a_single_tired_trope_caps_at_6_and_a_stack_does_not() -> None:
    """One sold idea stays at 6. Two or three traits, or a fresh twist, can score higher."""

    tropes = load_humor_lab().tired_tropes
    labels = {item["id"] for item in tropes}
    assert {
        "nurse_rash",
        "honk_anxiety",
        "eldest_third_parent",
        "mortician_naked",
        "emergency_contact",
        "talk_to_cows",
        "garage_fridge",
    } <= labels

    rash = LineReview(0, 9, 9, 9, sticker_buy_score=9, instantly_understandable=8)
    apply_trope_cap(rash, "WARNING: OFF-DUTY NURSE. DO NOT SHOW ME YOUR RASH.", tropes)
    assert rash.tired_trope is True
    assert rash.sticker_buy_score == 6

    bare_fridge = LineReview(0, 9, 9, 9, sticker_buy_score=9, instantly_understandable=8)
    apply_trope_cap(bare_fridge, "GARAGE FRIDGE CLUB", tropes)
    assert bare_fridge.sticker_buy_score == 6

    stacked_fridge = LineReview(0, 8, 8, 8, sticker_buy_score=8, instantly_understandable=8)
    apply_trope_cap(stacked_fridge, "GARAGE FRIDGE DADS, HANDS-ON-HIPS DIVISION", tropes)
    assert stacked_fridge.tired_trope is False
    assert stacked_fridge.sticker_buy_score == 8

    honk = LineReview(0, 8, 8, 8, sticker_buy_score=8, instantly_understandable=8)
    apply_trope_cap(honk, "HONK IF YOU HAVE ANXIETY. ACTUALLY, PLEASE DON'T.", tropes)
    assert honk.tired_trope is False

    bare_honk = LineReview(0, 9, 9, 9, sticker_buy_score=9, instantly_understandable=8)
    apply_trope_cap(bare_honk, "HONK IF YOU HAVE ANXIETY", tropes)
    assert bare_honk.sticker_buy_score == 6

    originals = [
        "RIZZLESS DIVORCED DADS WHO SMOKE BRISKET FOR FOURTEEN HOURS",
        "GIRL DAD IN HIS SWIFTIE ERA (AGAINST HIS WILL)",
        "HOT GIRL WALK GRANDPAS IN BRAND NEW NEW BALANCES",
    ]
    assert all(2 <= stacked_trait_count(line) <= 3 for line in originals)
    plain = SimpleNamespace(artwork_text="DADS", pattern="confession", comic_turn="ironic", phrase="")
    stacked = SimpleNamespace(
        artwork_text=originals[0],
        pattern="confession",
        comic_turn="ironic",
        phrase="",
    )
    kept = apply_line_critic(
        [plain, stacked],
        [
            LineReview(0, 8, 8, 8, sticker_buy_score=8, instantly_understandable=8),
            LineReview(1, 8, 8, 8, sticker_buy_score=8, instantly_understandable=8),
        ],
        keep_count=1,
        tone=HumorTone.DRY,
    )
    assert kept == [stacked]
