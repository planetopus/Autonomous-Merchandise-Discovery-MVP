"""Owner ratings calibrate the critic and can be extended by appending rows."""

from pathlib import Path
from unittest.mock import Mock

from merchandise_discovery.application.discovery_stage_executor import DiscoveryStageExecutor
from merchandise_discovery.domain.humor import (
    LineReview,
    apply_jargon_cap,
    apply_line_critic,
)
from merchandise_discovery.domain.models.common import HumorTone, PipelineVariant, SocialSource
from merchandise_discovery.domain.models.workflow import RunConfig, StageExecution, WorkflowRun
from merchandise_discovery.domain.pipelines.social_behavior_text import pipeline
from merchandise_discovery.infrastructure.ant_ratings_loader import (
    ant_calibration_block,
    load_ant_ratings,
    parse_ant_ratings,
)
from tests.live_reasoning import scripted_social_provider


def test_committed_ratings_match_ants_scores() -> None:
    """The bundled file is the calibration set from the teachers-and-coffee run."""

    ratings = {item.line: item for item in load_ant_ratings()}

    assert ratings["The First-Period Bus-Duty Coffee & Laminator Survivors"].verdict == "bad"
    assert ratings["The First-Period Bus-Duty Coffee & Laminator Survivors"].score == 3
    assert "don't get it" in ratings["The First-Period Bus-Duty Coffee & Laminator Survivors"].reason
    assert ratings["I teach water-only. My coffee gets tenure."].verdict == "funny"
    assert ratings["I teach water-only. My coffee gets tenure."].score == 8
    assert ratings["Do Not Enter Late With Coffee Unless It's Mine"].score == 6
    assert ratings["Hall duty: guarding a trash can for frappes."].score == 2
    assert ratings["Leave it on the counter, tardy."].reason == "poor setup"
    assert ratings["Calm through forty overdoses. Panics when the doorbell rings."].score == 10
    assert ratings["Hands on hips, auditing the beer fridge again."].verdict == "not funny"
    assert "no twist" in ratings["Hands on hips, auditing the beer fridge again."].reason
    assert ratings["BIG BACK DADS WHO 'TEST' THE BRISKET"].verdict == "very funny"
    assert ratings["BIG BACK DADS WHO 'TEST' THE BRISKET"].score == 9
    jargon = "too techy/inside-baseball"
    assert ratings["Patch Tuesday ate my raid night again."].score == 2
    assert ratings["Patch Tuesday ate my raid night again."].verdict == "not funny"
    assert jargon in ratings["Please open a ticket with HR about Steam."].reason
    assert ratings["Power-cycle has a 30-second cooldown, Karen."].verdict == "kind of funny"
    assert ratings["Power-cycle has a 30-second cooldown, Karen."].score == 6
    assert ratings["ALT-TAB PALADINS OF PRINTER HELL"].score == 6
    assert "printer hell" in ratings["ALT-TAB PALADINS OF PRINTER HELL"].reason
    assert ratings["GRANDMA HAS RIZZ (SHE GOT YOUR GRANDPA, DIDN'T SHE)"].score == 7
    assert "parenthetical" in ratings[
        "ELDEST DAUGHTER: THIRD PARENT SINCE AGE 6. BUILT DIFFERENT (DAMAGED)."
    ].reason
    calibration = ant_calibration_block(list(ratings.values()))
    assert "target group and most people" in calibration
    assert calibration.startswith("OWNER CALIBRATION")


def test_ratings_csv_accepts_an_appended_row(tmp_path: Path) -> None:
    """A new rating is one more row under the same header. Extra columns are ignored."""

    original = Path("data/ant_ratings.csv").read_text(encoding="utf-8")
    extended = original.rstrip() + '\n"New line, still a joke.",funny,9,lands,extra\n'
    path = tmp_path / "ant_ratings.csv"
    path.write_text(extended, encoding="utf-8")

    ratings = parse_ant_ratings(path.read_text(encoding="utf-8"))

    assert len(ratings) == len(parse_ant_ratings(original)) + 1
    assert ratings[-1].line == "New line, still a joke."
    assert ratings[-1].score == 9
    assert ratings[-1].verdict == "funny"


def test_insider_jargon_is_capped_and_a_universal_hook_is_not() -> None:
    """Patch Tuesday needs the jargon. Karen and printer hell can still score a 6."""

    jargon = LineReview(0, 9, 9, 9, sticker_buy_score=9, instantly_understandable=9)
    apply_jargon_cap(jargon, "Patch Tuesday ate my raid night again.")
    assert jargon.sticker_buy_score == 5
    assert jargon.insider_jargon is True

    hook = LineReview(0, 6, 6, 6, sticker_buy_score=6, instantly_understandable=6)
    apply_jargon_cap(hook, "Power-cycle has a 30-second cooldown, Karen.")
    assert hook.sticker_buy_score == 6
    assert hook.insider_jargon is False

    flagged = LineReview(0, 8, 8, 8, sticker_buy_score=8, instantly_understandable=8)
    flagged.insider_jargon = True
    apply_jargon_cap(flagged, "Please open a ticket with HR about Steam.")
    assert flagged.sticker_buy_score == 5


def test_unclear_lines_are_dropped_even_when_the_buy_score_is_high() -> None:
    """Instantly understandable is required. A clever line that takes a beat is cut."""

    from types import SimpleNamespace

    line = SimpleNamespace(artwork_text="A long compound club name", phrase="", pattern="confession")
    kept = apply_line_critic(
        [line],
        [
            LineReview(
                0,
                humor_landed=9,
                novelty=9,
                tone_match=9,
                reddit_upvote_score=9,
                sticker_buy_score=9,
                instantly_understandable=3,
            )
        ],
        keep_count=1,
        tone=HumorTone.DRY,
    )

    assert kept == []


def test_critic_prompt_opens_with_the_owner_ratings() -> None:
    """Ant's ratings are the first critic instruction and outrank the other rules."""

    run = WorkflowRun(
        title="Calibration",
        config=RunConfig(
            pipeline_variant=PipelineVariant.SOCIAL_BEHAVIOR_TEXT,
            social_sources=[SocialSource.REDDIT],
            social_query="teachers and coffee",
            social_candidate_count=1,
            social_niche_a="teachers",
            social_niche_b="coffee",
        ),
    )
    stage = StageExecution(run_id=run.run_id, stage_number=1, stage_name="Social text")
    candidate = pipeline.execute(
        pipeline.SocialBehaviorTextInput(
            sources=[SocialSource.REDDIT],
            query="teachers and coffee",
            candidate_count=1,
        )
    ).candidates[0].model_copy(
        update={
            "source_url": "https://reddit.com/r/Teachers/comments/abc/coffee",
            "artwork_text": "I teach water-only. My coffee gets tenure.",
            "pattern": "confession",
        }
    )
    provider = scripted_social_provider(
        pipeline.SocialBehaviorTextOutput(
            candidates=[candidate],
            search_summary="Teachers and coffee.",
        )
    )
    executor = DiscoveryStageExecutor(*(Mock() for _ in range(10)))
    executor._reasoning_provider = provider

    executor.execute(run, stage, executor.prepare(run, stage))

    critic = next(
        call.kwargs["system_prompt"]
        for call in provider.complete_structured.call_args_list
        if call.kwargs["response_model"].__name__ == "HumorCritiqueBatch"
    )
    assert critic.startswith("OWNER CALIBRATION")
    assert critic.index("OWNER CALIBRATION") < critic.index("sticker_buy_score")
    assert "My coffee gets tenure" in critic
    assert "Laminator Survivors" in critic
    assert "instantly_understandable" in critic
    assert "at most 5" in critic
    assert "at most 6" in critic
    assert "2 or 3" in critic
