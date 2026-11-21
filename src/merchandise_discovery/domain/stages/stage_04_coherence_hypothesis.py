"""Stage 4: select research-worthy intersections with structured AI reasoning.

Stage 3 creates the candidate set. This module owns the semantic decision about which candidates
are worth researching next, while the application layer remains responsible for provider access
and the deterministic trust boundary. The no-provider path is intentionally limited to fixture
mode so local demos remain runnable; live provider failures are surfaced by the executor.
"""

from pydantic import BaseModel, Field

from merchandise_discovery.domain.models.artifacts import IdentityIntersection


class CoherenceInput(BaseModel):
    """All Stage 3 candidates and the exact research budget for the next stage."""

    intersections: list[IdentityIntersection]
    max_researched_niches: int = Field(default=3, ge=1, le=100)


class ResearchSelection(BaseModel):
    """One AI-selected candidate with the reasoning behind the choice."""

    intersection_id: str = Field(min_length=1)
    selection_reason: str = Field(min_length=1, max_length=500)
    coherence_score: float = Field(
        ge=0,
        le=10,
        description="Coherence score from 0.0 to 10.0, not a probability or confidence value.",
    )
    research_value_score: float = Field(
        ge=0,
        le=10,
        description="Research value score from 0.0 to 10.0, not a probability or confidence value.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "Confidence in this selection as a probability-like value from 0.0 to 1.0. "
            "This is not a 0-to-10 score."
        ),
    )


class Stage4ReasoningOutput(BaseModel):
    """Exact structured response expected from OpenAI for Stage 4."""

    selections: list[ResearchSelection] = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=500)


class CoherenceOutput(BaseModel):
    """Complete candidate audit plus the bounded set passed to niche research."""

    intersections: list[IdentityIntersection]
    selected_intersection_ids: list[str] = Field(default_factory=list)
    provider_selections_count: int = Field(default=0, ge=0)
    summary: str = ""
    model: str = "deterministic"


def reasoning_instructions() -> str:
    """Return the provider contract for a mixed, non-duplicate collision portfolio.

    Stage 4 receives independent candidates but produces one bounded research portfolio. The
    prompt therefore makes set-level diversity an explicit decision criterion instead of allowing
    the provider to select several individually strong variations of the same joke.
    """

    return (
        "You are a merchandise discovery reasoning provider executing Stage 4, AI Coherence and "
        "Research Selection. Review all supplied intersections as written, then select only the "
        "candidates needed by the next research stage. Never create, remove, rename, or combine "
        "candidates, and preserve selected intersection IDs exactly. Treat the selected candidates "
        "as one research portfolio, not as independent winners. First score each candidate as a "
        "collision: unexpectedness, whether a real person is both, and whether a stranger still "
        "gets it. Do not prefer natural pairs or shared affinity tags. Then make a second "
        "portfolio-level comparison and prefer candidates that differ in primary audience, "
        "core activity, emotional job, repeated ritual, and likely visual language. Do not select the "
        "top individual scores when the candidates would produce similar concepts or artwork. Reject "
        "duplicate jokes. For example, several recent-relocator candidates about making a new "
        "city feel like home are one duplicate joke even if one uses music, one cycling, and one "
        "board games; choose only one of them when distinct alternatives are available. Mix the "
        "finalists across warm, dry, and dark humor. Dark and bleak angles are allowed when they "
        "stay specific. Do not drop a collision only because it is not hopeful or not giftable. "
        "Avoid candidates whose central promise is merely generic lifestyle aspiration, demographic "
        "overlap, isolation, or consumption. Each selection_reason must explain both the candidate's "
        "specific lived experience and what distinct portfolio angle it contributes. Return only "
        "the requested structured output."
    )


def _validate_selection_ids(
    intersections: list[IdentityIntersection],
    selections: list[ResearchSelection],
    *,
    requested_count: int,
) -> dict[str, ResearchSelection]:
    """Validate provider IDs, duplicates, and the exact downstream research budget."""

    expected = {item.intersection_id for item in intersections}
    selection_ids = [item.intersection_id for item in selections]
    if len(selection_ids) != len(set(selection_ids)):
        raise ValueError("Stage 4 provider output contains duplicate intersection IDs.")
    unknown = sorted(set(selection_ids) - expected)
    if unknown:
        raise ValueError(f"Stage 4 provider output contains unknown intersection IDs: {unknown}.")

    expected_count = min(requested_count, len(intersections))
    if len(selections) != expected_count:
        raise ValueError(
            "Stage 4 provider must select exactly the configured research count; "
            f"expected={expected_count}, received={len(selections)}."
        )
    return {selection.intersection_id: selection for selection in selections}


def _materialize_selection(
    input_data: CoherenceInput,
    selections: list[ResearchSelection],
    *,
    model: str,
    summary: str,
    generation_method: str = "provider",
) -> CoherenceOutput:
    """Attach selection metadata to trusted candidates and retain non-selected records for audit."""

    by_id = _validate_selection_ids(
        input_data.intersections,
        selections,
        requested_count=input_data.max_researched_niches,
    )
    selected_ids = [selection.intersection_id for selection in selections]
    materialized: list[IdentityIntersection] = []
    for intersection in input_data.intersections:
        selection = by_id.get(intersection.intersection_id)
        if selection is None:
            materialized.append(
                intersection.model_copy(
                    update={
                        "eligible_for_research": False,
                        "filter_reason": "Not selected by AI for the configured research budget.",
                    }
                )
            )
            continue

        if len(intersection.identities) < 2 or any(
            not str(identity).strip() for identity in intersection.identities
        ):
            raise ValueError(
                f"Stage 4 selected intersection {intersection.intersection_id} is structurally invalid."
            )
        categories = {
            str(category).casefold()
            for category in intersection.metadata.get("categories", [])
        }
        pair_kind = str(intersection.metadata.get("pair_kind") or "")
        crosses_lives = pair_kind in {
            "job_x_hobby",
            "identity_x_life_situation",
            "two_communities",
            "two_lives",
        }
        if categories and not crosses_lives and not {"audience", "interest"}.issubset(categories):
            raise ValueError(
                f"Stage 4 selected intersection {intersection.intersection_id} must combine "
                "two different lives."
            )

        materialized.append(
            intersection.model_copy(
                update={
                    "coherence_score": round(selection.coherence_score, 2),
                    "experience_hypotheses": [selection.selection_reason],
                    "eligible_for_research": True,
                    "filter_reason": None,
                    "metadata": {
                        **intersection.metadata,
                        "selection_reason": selection.selection_reason,
                        "research_value_score": selection.research_value_score,
                        "coherence_confidence": selection.confidence,
                        "coherence_generation_method": generation_method,
                        "coherence_model": model,
                    },
                }
            )
        )

    return CoherenceOutput(
        intersections=materialized,
        selected_intersection_ids=selected_ids,
        provider_selections_count=len(selections),
        summary=summary,
        model=model,
    )


def _joke_key(intersection: IdentityIntersection) -> str:
    """Identify one joke so the fixture portfolio does not keep the same collision twice."""

    return "|".join(sorted(" ".join(str(identity).casefold().split()) for identity in intersection.identities))


def _apply_deterministic_selection(input_data: CoherenceInput) -> CoherenceOutput:
    """Provide a reproducible fixture result without pretending a provider made the decision."""

    ordered = sorted(
        input_data.intersections,
        key=lambda intersection: (
            -int(intersection.metadata.get("collision_score", intersection.metadata.get("candidate_score", 0))),
            intersection.intersection_id,
        ),
    )
    selected: list[IdentityIntersection] = []
    seen_jokes: set[str] = set()
    for intersection in ordered:
        key = _joke_key(intersection)
        if key in seen_jokes:
            continue
        seen_jokes.add(key)
        selected.append(intersection)
        if len(selected) >= input_data.max_researched_niches:
            break
    if len(selected) < min(input_data.max_researched_niches, len(ordered)):
        for intersection in ordered:
            if intersection in selected:
                continue
            selected.append(intersection)
            if len(selected) >= input_data.max_researched_niches:
                break
    tones = ("warm", "dry", "dark")
    selections = [
        ResearchSelection(
            intersection_id=intersection.intersection_id,
            selection_reason=(
                "Selected from the collision score as a "
                f"{tones[index % len(tones)]} portfolio angle, skipping duplicate jokes."
            ),
            coherence_score=min(
                10.0,
                4.0 + int(intersection.metadata.get("collision_score", 0)) / 4,
            ),
            research_value_score=5.0,
            confidence=1.0,
        )
        for index, intersection in enumerate(selected)
    ]
    output = _materialize_selection(
        input_data,
        selections,
        model="deterministic",
        summary=(
            f"Selected {len(selected)} of {len(input_data.intersections)} collisions "
            "deterministically for fixture mode."
        ),
        generation_method="deterministic",
    )
    angled = []
    tone_by_id = {
        intersection.intersection_id: tones[index % len(tones)]
        for index, intersection in enumerate(selected)
    }
    for intersection in output.intersections:
        tone = tone_by_id.get(intersection.intersection_id)
        if tone is None:
            angled.append(intersection)
            continue
        angled.append(
            intersection.model_copy(
                update={"metadata": {**intersection.metadata, "humor_angle": tone}}
            )
        )
    return output.model_copy(update={"provider_selections_count": 0, "intersections": angled})


def execute(
    input_data: CoherenceInput,
    *,
    reasoning_output: Stage4ReasoningOutput | None = None,
    model: str = "deterministic",
) -> CoherenceOutput:
    """Materialize direct AI selection, or use the deterministic no-provider fixture path."""

    if not input_data.intersections:
        raise ValueError("Stage 4 requires at least one Stage 3 intersection.")
    if reasoning_output is not None:
        return _materialize_selection(
            input_data,
            reasoning_output.selections,
            model=model,
            summary=reasoning_output.summary,
        )
    return _apply_deterministic_selection(input_data)
