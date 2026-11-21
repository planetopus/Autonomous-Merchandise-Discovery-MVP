"""Playbook shapes, including the high-priority patterns, never store sample slogans."""

from types import SimpleNamespace

from merchandise_discovery.domain.humor import (
    LineReview,
    NichePairCandidate,
    apply_line_critic,
    keep_strong_pairs,
)
from merchandise_discovery.domain.humor_playbook import build_playbook, playbook_prompt
from merchandise_discovery.domain.models.common import HumorTone
from merchandise_discovery.infrastructure.humor_reference_loader import (
    bundled_humor_reference_csv,
    parse_humor_reference_csv,
)

FORBIDDEN = (
    "thicc dads",
    "vape for christ",
    "private sign do not read",
    "pre-grieving",
    "back off santa",
    "earring backs",
    "chernobyl",
    "nosey neighbor",
    "my neighbor is a karen",
)


def test_priority_patterns_lead_and_do_not_quote_the_source_lines() -> None:
    """The stacked-club shape is first, and none of the flagged slogans are stored."""

    references = parse_humor_reference_csv(
        bundled_humor_reference_csv().read_text(encoding="utf-8-sig")
    )
    playbook = build_playbook(references)
    prompt = playbook_prompt(playbook)

    assert playbook["patterns"][0]["id"] == "absurd_identity_stack"
    assert playbook["patterns"][0]["examples"] == []
    ids = [item["id"] for item in playbook["patterns"] if item.get("priority")]
    assert ids[:3] == [
        "absurd_identity_stack",
        "self_defeating_sign",
        "cheerful_dark_label",
    ]
    assert "absurd_identity_stack" in prompt
    assert "At least two candidates" in prompt
    assert "co-occur" in prompt
    assert "register" in prompt
    blob = (prompt + " ".join(item["guidance"] for item in playbook["patterns"])).casefold()
    saved = bundled_humor_reference_csv().parents[0].joinpath("humor_playbook.json").read_text(
        encoding="utf-8"
    )
    blob = blob + " " + saved.casefold()
    for phrase in FORBIDDEN:
        assert phrase not in blob


def test_pairs_under_7_on_either_axis_are_dropped() -> None:
    """Both shared life and recognizability have to clear 7."""

    pairs = [
        NichePairCandidate(
            niche_a="nurses",
            niche_b="true crime",
            shared_life_score=9,
            recognizability_score=8,
            reason="Same night.",
        ),
        NichePairCandidate(
            niche_a="dads",
            niche_b="grilling",
            shared_life_score=8,
            recognizability_score=6,
            reason="Recognizable, but the second score is short.",
        ),
    ]

    kept = keep_strong_pairs(pairs)

    assert [pair.niche_b for pair in kept] == ["true crime"]


def test_critic_drops_a_line_whose_three_scores_average_under_7() -> None:
    """Reddit upvote, sticker buy, and originality are averaged."""

    line = SimpleNamespace(artwork_text="Still a title pun", phrase="")
    kept = apply_line_critic(
        [line],
        [
            LineReview(
                0,
                humor_landed=8,
                novelty=4,
                tone_match=8,
                reddit_upvote_score=9,
                sticker_buy_score=6,
            )
        ],
        keep_count=1,
        tone=HumorTone.DRY,
    )

    assert kept == []


def test_a_long_literal_stack_is_not_a_club_name() -> None:
    """Identity-stack lines have to be short and in capitals."""

    from merchandise_discovery.domain.humor import identity_stack_is_too_long

    literal = "The First-Period Bus-Duty Coffee & Laminator Survivors"
    assert identity_stack_is_too_long(literal, "absurd_identity_stack")
    assert not identity_stack_is_too_long("THICC DADS WHO VAPE FOR CHRIST", "absurd_identity_stack")
    assert not identity_stack_is_too_long(literal, "confession")


def test_member_buy_score_outweighs_a_generic_reddit_score() -> None:
    """A member who would buy the line is kept even when Reddit would not upvote it."""

    bought = SimpleNamespace(artwork_text="Our small group brings the snacks", phrase="")
    upvoted = SimpleNamespace(artwork_text="Random words stacked for shock", phrase="")
    kept = apply_line_critic(
        [upvoted, bought],
        [
            LineReview(
                0,
                humor_landed=9,
                novelty=9,
                tone_match=9,
                reddit_upvote_score=10,
                sticker_buy_score=4,
            ),
            LineReview(
                1,
                humor_landed=8,
                novelty=8,
                tone_match=8,
                reddit_upvote_score=3,
                sticker_buy_score=9,
            ),
        ],
        keep_count=2,
        tone=HumorTone.DRY,
    )

    assert kept == [bought]
