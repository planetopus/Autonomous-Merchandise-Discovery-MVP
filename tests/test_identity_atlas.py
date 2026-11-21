"""The identity atlas is optional and tolerant of the lab's field names."""

import random
from unittest.mock import Mock

from merchandise_discovery.application.discovery_stage_executor import DiscoveryStageExecutor
from merchandise_discovery.domain.humor import NichePairBatch, NichePairCandidate
from merchandise_discovery.domain.models.common import PipelineVariant, SocialSource
from merchandise_discovery.domain.models.usage import UsageMetrics
from merchandise_discovery.domain.models.workflow import RunConfig, StageExecution, WorkflowRun
from merchandise_discovery.domain.pipelines.social_behavior_text import pipeline
from merchandise_discovery.infrastructure.identity_atlas_loader import (
    IdentityAtlas,
    IdentitySubgroup,
    OverlapCombo,
    SlangTerm,
    diversity_factor,
    infer_who_its_for,
    is_narrow_identity,
    load_identity_atlas,
    sample_overlap_pairs,
    split_identity_names,
)
from tests.live_reasoning import scripted_social_provider


def test_loader_accepts_wrapped_objects_and_alternate_keys(tmp_path) -> None:
    """A list, a wrapped object, comma-separated traits, and nested self-words all load."""

    folder = tmp_path / "identity_atlas"
    folder.mkdir()
    (folder / "identity_atlas.json").write_text(
        """
        {"subgroups": [
          {
            "label": "Night-shift nurses",
            "dimension": "job",
            "true_traits": "charts after clock-out, podcast in the car",
            "self_vs_outsider": {"self": ["on nights"], "outsider": ["nurse life"]},
            "co_occurrences": ["True-crime listeners"],
            "buyer_pride_score": 8,
            "dark_tolerance": 6,
            "self_ownable_note": "They can claim the charting joke. Do not mock patients."
          }
        ]}
        """,
        encoding="utf-8",
    )
    (folder / "slang_lexicon.json").write_text(
        """
        [{"word": "delulu", "definition": "delusional optimism", "register": "gen z", "mismatch": 9},
         {"term": "rizz", "meaning": "charm", "register": "gen alpha", "mismatch_score": 4}]
        """,
        encoding="utf-8",
    )
    (folder / "overlap_combos.json").write_text(
        """
        {"combos": [
          {"subgroups": ["Night-shift nurses", "True-crime listeners"],
           "detail": "the drive home is an episode",
           "hook": "delulu",
           "buyerPride": 9}
        ]}
        """,
        encoding="utf-8",
    )

    atlas = load_identity_atlas(folder)

    assert atlas.subgroups[0].name == "Night-shift nurses"
    assert atlas.subgroups[0].traits == ["charts after clock-out", "podcast in the car"]
    assert atlas.subgroups[0].self_words == ["on nights"]
    assert atlas.subgroups[0].overlaps == ["True-crime listeners"]
    assert atlas.subgroups[0].self_ownable.startswith("They can claim")
    assert atlas.slang[0].term == "delulu"
    assert atlas.slang[0].mismatch_score == 9
    assert atlas.combos[0].names[1] == "True-crime listeners"
    assert load_identity_atlas(tmp_path / "missing").subgroups == []


def test_selling_identities_are_sampled_ahead_of_equal_pride() -> None:
    """A trending atlas identity outranks an equal-pride pair the market is not selling."""

    atlas = IdentityAtlas(
        combos=[
            OverlapCombo(names=["Church dads", "Vaping"], buyer_pride=5),
            OverlapCombo(names=["ADHD folks", "Coffee"], buyer_pride=5),
        ]
    )
    hits = 0
    for seed in range(30):
        picked = sample_overlap_pairs(
            atlas,
            limit=1,
            rng=random.Random(seed),
            trend={"adhd": 4.0},
        )
        if picked and picked[0]["niche_a"] == "ADHD folks":
            hits += 1
    assert hits >= 22


def test_overlap_sampling_prefers_buyer_pride() -> None:
    """A high buyer-pride combo is chosen far more often than a low-pride one."""

    atlas = IdentityAtlas(
        combos=[
            OverlapCombo(names=["Church dads", "Vaping"], buyer_pride=10),
            OverlapCombo(names=["Accountants", "Scuba"], buyer_pride=0.1),
        ]
    )
    hits = 0
    for seed in range(40):
        picked = sample_overlap_pairs(atlas, limit=1, rng=random.Random(seed))
        if picked and picked[0]["niche_a"] == "Church dads":
            hits += 1
    assert hits >= 30


def test_unused_identities_are_preferred_and_familiar_groups_get_no_boost() -> None:
    """Recent dads are downweighted. An unused group with the same pride is not."""

    assert diversity_factor(["dads"], {}) == diversity_factor(["beekeepers"], {})
    atlas = IdentityAtlas(
        combos=[
            OverlapCombo(names=["Church dads", "Garages"], buyer_pride=5),
            OverlapCombo(names=["Beekeepers", "Weeknight cooks"], buyer_pride=5),
        ]
    )
    hits = 0
    for seed in range(30):
        picked = sample_overlap_pairs(
            atlas,
            limit=1,
            rng=random.Random(seed),
            avoid=["church dads", "garage"],
        )
        if picked and picked[0]["niche_a"] == "Beekeepers":
            hits += 1
    assert hits >= 20
    buyers = infer_who_its_for(
        ["DIY"],
        ["Church dads", "beer"],
        [IdentitySubgroup(name="Church dads", overlaps=["beer drinkers"])],
    )
    assert buyers[0] == "DIY"
    assert 2 <= len(buyers) <= 4


def test_one_field_can_hold_one_identity_or_several() -> None:
    """Niche fields no longer require a pair, and commas split several identities."""

    single = RunConfig(
        pipeline_variant=PipelineVariant.SOCIAL_BEHAVIOR_TEXT,
        social_sources=[SocialSource.REDDIT],
        social_query="weekend plans",
        social_niche_a="church dads",
    )
    several = RunConfig(
        pipeline_variant=PipelineVariant.SOCIAL_BEHAVIOR_TEXT,
        social_sources=[SocialSource.REDDIT],
        social_query="weekend plans",
        social_niche_a="church dads, weekend grilling",
        social_niche_b="vaping",
    )

    assert single.social_niche_b == ""
    assert split_identity_names(several.social_niche_a, several.social_niche_b) == [
        "church dads",
        "weekend grilling",
        "vaping",
    ]


def test_live_run_feeds_atlas_traits_slang_and_self_ownable_notes(monkeypatch) -> None:
    """A supplied identity pulls traits into the draft and the self-ownable note into the critic."""

    atlas = IdentityAtlas(
        subgroups=[
            IdentitySubgroup(
                name="Church dads",
                dimension="religion",
                traits=["Sunday service", "smokes outside after"],
                self_words=["blessed"],
                outsider_words=["church guy"],
                overlaps=["Vaping"],
                buyer_pride=9,
                dark_tolerance=4,
                self_ownable="They can claim the habit. Do not mock the faith.",
            )
        ],
        slang=[
            SlangTerm(term="delulu", meaning="delusional optimism", register="gen z", mismatch_score=9),
            SlangTerm(term="rizz", meaning="charm", register="gen alpha", mismatch_score=3),
        ],
        combos=[OverlapCombo(names=["Church dads", "Vaping"], buyer_pride=9, slang_hook="delulu")],
    )
    monkeypatch.setattr(
        "merchandise_discovery.application.discovery_stage_executor.load_identity_atlas",
        lambda: atlas,
    )
    run = WorkflowRun(
        title="Atlas",
        config=RunConfig(
            pipeline_variant=PipelineVariant.SOCIAL_BEHAVIOR_TEXT,
            social_sources=[SocialSource.REDDIT],
            social_query="sunday habits",
            social_candidate_count=1,
            social_niche_a="Church dads, Vaping",
        ),
    )
    stage = StageExecution(run_id=run.run_id, stage_number=1, stage_name="Social text")
    candidate = pipeline.execute(
        pipeline.SocialBehaviorTextInput(
            sources=[SocialSource.REDDIT],
            query="sunday habits",
            candidate_count=1,
        )
    ).candidates[0].model_copy(
        update={
            "source_url": "https://reddit.com/r/daddit/comments/abc/sunday",
            "artwork_text": "My small group brings the snacks",
            "pattern": "confession",
        }
    )
    provider = scripted_social_provider(
        pipeline.SocialBehaviorTextOutput(
            candidates=[candidate],
            search_summary="Dads who stay after the service.",
        )
    )
    executor = DiscoveryStageExecutor(*(Mock() for _ in range(10)))
    executor._reasoning_provider = provider

    result = executor.execute(run, stage, executor.prepare(run, stage))
    assert result.output_data["atlas_subgroups_loaded"] == 1

    writer = next(
        call.kwargs["user_prompt"]
        for call in provider.complete_structured.call_args_list
        if call.kwargs["response_model"].__name__ != "HumorCritiqueBatch"
    )
    critic = next(
        call.kwargs["system_prompt"]
        for call in provider.complete_structured.call_args_list
        if call.kwargs["response_model"].__name__ == "HumorCritiqueBatch"
    )
    assert "Sunday service" in writer
    assert "delulu" in writer
    assert "Do not mock the faith" in critic
    assert provider.complete_structured.call_count == 2


def test_published_atlas_loads_and_the_auto_pick_stays_broad() -> None:
    """Runtime loads the published atlas, and occupation-by-hobby pairs are not sampled."""

    from types import SimpleNamespace

    atlas = load_identity_atlas()
    assert len(atlas.subgroups) >= 500
    support = atlas.lookup("it_support")
    assert support is not None
    assert support.name == "IT support"
    assert is_narrow_identity(support)
    picked = sample_overlap_pairs(atlas, limit=10, rng=random.Random(0))
    assert picked
    for item in picked:
        for side in [item["niche_a"], *item["niche_b"].split(" + ")]:
            group = atlas.lookup(side)
            assert group is None or not is_narrow_identity(group)
            assert "_" not in side

    buyers = infer_who_its_for(
        ["Gamers", "energy_drink_people", "introverts", "it_support"],
        ["it_support", "gamers"],
        None,
        atlas,
    )
    assert buyers[0] == "Gamers"
    assert "IT support" in buyers
    assert "Energy drink addicts" not in buyers
    assert all("_" not in label for label in buyers)

    executor = DiscoveryStageExecutor(*(Mock() for _ in range(10)))
    provider = Mock()
    provider.complete_structured.return_value = SimpleNamespace(
        output=NichePairBatch(
            pairs=[
                NichePairCandidate(
                    niche_a="IT support",
                    niche_b="Gamers",
                    shared_life_score=9,
                    recognizability_score=9,
                    reason="Both sit at a computer.",
                )
            ]
        ),
        usage=UsageMetrics(),
    )
    executor._reasoning_provider = provider
    bank = [{"niche_a": "Church dads", "niche_b": "Vapers"}]
    meta, _usage, warning = executor._score_niche_pairs(SimpleNamespace(identity=""), bank, [])
    assert meta["niche_pair_a"] == "Church dads"
    assert meta["niche_pair_b"] == "Vapers"
    assert warning == ""
    assert "identity atlas" in meta["pairing_reason"]
