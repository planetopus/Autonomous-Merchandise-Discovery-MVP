"""Collision scoring, Reddit comments, marketplace saturation, and the humor critic."""

from types import SimpleNamespace

from merchandise_discovery.domain.humor import LineReview, apply_line_critic
from merchandise_discovery.domain.models.artifacts import IdentityIntersection, MerchandiseConcept
from merchandise_discovery.domain.models.common import ConceptVerdict, HumorTone, SeedCategory
from merchandise_discovery.domain.stages.stage_02_identity_expansion import ExpandedIdentity
from merchandise_discovery.domain.stages.stage_03_intersection_generation import collision_scores
from merchandise_discovery.domain.stages.stage_04_coherence_hypothesis import CoherenceInput
from merchandise_discovery.domain.stages.stage_04_coherence_hypothesis import (
    execute as execute_coherence,
)
from merchandise_discovery.domain.stages.stage_11_similarity_ip_check import (
    SaturationFinding,
    SimilarityCheckInput,
)
from merchandise_discovery.domain.stages.stage_11_similarity_ip_check import (
    execute as execute_similarity,
)
from merchandise_discovery.domain.stages.stage_12_final_selection import (
    FinalSelectionEvaluation,
    FinalSelectionInput,
    Stage12ReasoningOutput,
)
from merchandise_discovery.domain.stages.stage_12_final_selection import (
    execute as execute_final_selection,
)
from merchandise_discovery.infrastructure.providers.marketplace_saturation import MarketplaceChecker
from merchandise_discovery.infrastructure.providers.reddit_reader import RedditReader


def _identity(category: SeedCategory, value: str, tags: list[str], seed: str) -> ExpandedIdentity:
    return ExpandedIdentity(
        source_seed_id=seed,
        source_seed_name=value,
        category=category,
        dimension_type="core",
        value=value,
        affinity_tags=tags,
        priority=5,
    )


def test_collision_score_prefers_two_different_lives_over_shared_tags() -> None:
    """A job crossed with a hobby outranks two identities that share affinity tags."""

    nurse = _identity(SeedCategory.AUDIENCE, "night-shift nurses", ["hospital"], "job")
    dogs = _identity(SeedCategory.INTEREST, "pit bull rescue", ["dogs"], "hobby")
    shared_left = _identity(SeedCategory.AUDIENCE, "night-shift nurses", ["calm", "ritual", "home"], "a")
    shared_right = _identity(SeedCategory.AUDIENCE, "night-shift nurses", ["calm", "ritual", "home"], "b")

    collision = collision_scores((nurse, dogs))
    natural = collision_scores((shared_left, shared_right))

    assert collision["pair_kind"] == "job_x_hobby"
    assert collision["collision_score"] > natural["collision_score"]
    assert collision["unexpectedness"] > natural["unexpectedness"]


def test_stage_four_skips_a_duplicate_joke_when_another_collision_exists() -> None:
    """The fixture portfolio keeps a second collision instead of the same joke twice."""

    first = IdentityIntersection(
        intersection_id="same-joke-a",
        run_id="run",
        identities=["Night nurses", "Pit bulls"],
        metadata={"collision_score": 20, "candidate_score": 20, "pair_kind": "job_x_hobby"},
    )
    duplicate = IdentityIntersection(
        intersection_id="same-joke-b",
        run_id="run",
        identities=["Pit bulls", "Night nurses"],
        metadata={"collision_score": 19, "candidate_score": 19, "pair_kind": "job_x_hobby"},
    )
    other = IdentityIntersection(
        intersection_id="other-joke",
        run_id="run",
        identities=["Teachers", "Houseplants"],
        metadata={"collision_score": 12, "candidate_score": 12, "pair_kind": "job_x_hobby"},
    )

    result = execute_coherence(
        CoherenceInput(intersections=[first, duplicate, other], max_researched_niches=2)
    )

    assert result.selected_intersection_ids == ["same-joke-a", "other-joke"]
    angles = {
        item.intersection_id: item.metadata.get("humor_angle")
        for item in result.intersections
        if item.eligible_for_research
    }
    assert set(angles.values()) == {"warm", "dry"}


def test_dark_critic_does_not_drop_a_bleak_line_for_low_giftability() -> None:
    """A landed dark joke outranks a safer line when dark is the requested tone."""

    bleak = SimpleNamespace(artwork_text="Still Charting", phrase="")
    safe = SimpleNamespace(artwork_text="Coffee First", phrase="")
    kept = apply_line_critic(
        [safe, bleak],
        [
            LineReview(0, humor_landed=4, novelty=4, tone_match=4, giftability=10),
            LineReview(1, humor_landed=9, novelty=8, tone_match=9, giftability=0),
        ],
        keep_count=1,
        tone=HumorTone.DARK,
    )

    assert kept == [bleak]


def test_dark_finalist_score_ignores_giftability() -> None:
    """Stage 12 does not let giftability veto a dark line."""

    dark_line = MerchandiseConcept(
        concept_id="dark",
        run_id="run",
        niche_id="niche",
        phrase="Still Charting",
        description="A bleak shift joke.",
        verdict=ConceptVerdict.KEEP,
        overall_score=8,
    )
    evaluation = FinalSelectionEvaluation(
        concept_id="dark",
        distinctiveness=8,
        emotional_recognition=8,
        natural_wording=8,
        giftability=0,
        commercial_appeal=8,
        visual_potential=8,
        rationale="The bleak line lands for the requested tone.",
    )

    result = execute_final_selection(
        FinalSelectionInput(concepts=[dark_line], max_finalists=1, humor_tone="dark"),
        reasoning_output=Stage12ReasoningOutput(evaluations=[evaluation], summary="Dark tone."),
    )

    assert result.finalists[0].selection_score == 8


def test_marketplace_check_drops_a_crowded_phrase_and_skips_without_a_live_client() -> None:
    """Etsy counts drop crowded lines. Fixture mode records a skip and keeps the line."""

    class Response:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class Client:
        def get(self, url, params=None, headers=None):
            assert "etsy.com" in url
            assert headers["x-api-key"] == "test-key"
            return Response({"count": 80})

        def close(self):
            return None

    crowded = MerchandiseConcept(
        concept_id="crowded",
        run_id="run",
        niche_id="niche",
        phrase="Nurse Life",
        description="A crowded phrase.",
        verdict=ConceptVerdict.KEEP,
        overall_score=9,
    )
    fresh = MerchandiseConcept(
        concept_id="fresh",
        run_id="run",
        niche_id="niche",
        phrase="Chart Goblin",
        description="A fresher phrase.",
        verdict=ConceptVerdict.KEEP,
        overall_score=7,
    )
    live = MarketplaceChecker(etsy_api_key="test-key", live=True, client=Client())
    findings = live.check([("crowded", "Nurse Life"), ("fresh", "Chart Goblin")])
    fresh_count = next(item for item in findings if item.item_id == "fresh")
    # The fake client returns 80 for every call, so both are crowded. One must remain.
    result = execute_similarity(
        SimilarityCheckInput(
            concepts=[crowded, fresh],
            saturation=[
                SaturationFinding(
                    concept_id=item.item_id,
                    count=item.count,
                    source=item.source,
                    note=item.note,
                )
                for item in findings
            ],
        )
    )
    assert fresh_count.count == 80
    assert len(result.survivors) == 1
    assert len(result.rejected) == 1

    skipped = MarketplaceChecker(live=False).check([("crowded", "Nurse Life")])
    assert skipped[0].source == "skipped"
    assert skipped[0].count is None


def test_reddit_reader_is_slow_uses_a_user_agent_and_reads_top_comments() -> None:
    """Public JSON reads pause between calls and keep the highest-scored comment."""

    now = {"value": 0.0}
    slept: list[float] = []

    def clock() -> float:
        return now["value"]

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now["value"] += seconds

    search = {
        "data": {
            "children": [
                {
                    "data": {
                        "id": "abc",
                        "title": "Night shift",
                        "permalink": "/r/nursing/comments/abc/night_shift/",
                        "score": 20,
                        "stickied": False,
                    }
                }
            ]
        }
    }
    comments = [
        {"data": {"children": []}},
        {
            "data": {
                "children": [
                    {
                        "kind": "t1",
                        "data": {
                            "author": "nurse",
                            "body": "I chart until the sun comes up and then I walk the dog.",
                            "score": 12,
                            "permalink": "/r/nursing/comments/abc/night_shift/c1/",
                        },
                    },
                    {
                        "kind": "t1",
                        "data": {
                            "author": "AutoModerator",
                            "body": "This is an automated community message for new posts.",
                            "score": 1,
                            "permalink": "/r/nursing/comments/abc/night_shift/c2/",
                        },
                    },
                ]
            }
        },
    ]

    class Response:
        def __init__(self, payload, status=200, headers=None):
            self._payload = payload
            self.status_code = status
            self.headers = headers or {}

        def json(self):
            return self._payload

    class Client:
        def __init__(self):
            self.calls = []

        def get(self, url, params=None, headers=None):
            self.calls.append((url, headers))
            if url.endswith("search.json"):
                return Response(search)
            return Response(comments)

    client = Client()
    reader = RedditReader(client=client, min_interval_seconds=2.0, sleep=sleep, clock=clock)
    found = reader.collect("night shift nurses pit bulls")

    assert len(client.calls) == 2
    assert slept == [2.0]
    assert client.calls[0][1]["User-Agent"].startswith("autonomous-merchandise-discovery/0.1")
    assert len(found) == 1
    assert found[0].body.startswith("I chart until the sun")
    assert found[0].url.startswith("https://www.reddit.com/")
