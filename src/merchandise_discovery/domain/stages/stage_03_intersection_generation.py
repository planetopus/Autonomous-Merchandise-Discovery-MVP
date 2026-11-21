"""Stage 3: use bounded AI proposals to generate identity intersections.

This module owns the provider response contract and the deterministic safety boundary around it.
The application layer supplies the complete Stage 2 identity catalog to a reasoning provider, but
the provider can only refer to stable catalog references. The resulting intersections are built
from application-owned records, so AI cannot invent identities or bypass candidate limits.
"""

import hashlib
import re

from pydantic import BaseModel, Field

from merchandise_discovery.domain.models.artifacts import IdentityIntersection
from merchandise_discovery.domain.stages.stage_02_identity_expansion import ExpandedIdentity


class IntersectionGenerationInput(BaseModel):
    """Expanded identities and the configured candidate bound."""

    identities: list[ExpandedIdentity]
    max_intersections: int = Field(ge=1, le=5000)


class IntersectionGenerationOutput(BaseModel):
    """Candidate intersections retained for coherence scoring."""

    intersections: list[IdentityIntersection]
    provider_proposals_count: int = Field(default=0, ge=0)
    provider_rejected_count: int = Field(default=0, ge=0)
    summary: str = ""
    model: str = "deterministic"


class IntersectionProposal(BaseModel):
    """One AI-proposed combination of references from the supplied identity catalog."""

    identity_refs: list[str] = Field(min_length=2, max_length=6)
    composition_rationale: str = Field(min_length=1, max_length=400)
    distinctiveness: int = Field(ge=1, le=10)


class Stage3ReasoningOutput(BaseModel):
    """Exact structured response expected from OpenAI for Stage 3."""

    proposals: list[IntersectionProposal] = Field(min_length=1, max_length=50)
    summary: str = Field(min_length=1, max_length=500)


def identity_ref(identity: ExpandedIdentity) -> str:
    """Return a stable, opaque reference for one identity value.

    Stage 3 sends these references instead of asking the provider to repeat full records. The hash
    prevents collisions when one seed contains multiple dimensions with the same type, while the
    readable prefix keeps provider prompts and persisted audit data inspectable.
    """

    normalized = " ".join(identity.value.casefold().split())
    value_hash = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    dimension = re.sub(r"[^a-z0-9]+", "_", identity.dimension_type.casefold()).strip("_")
    return f"{identity.source_seed_id}:{dimension}:{value_hash}"


def build_identity_catalog(identities: list[ExpandedIdentity]) -> list[dict]:
    """Serialize every selected Stage 2 identity into the provider's trusted reference catalog."""

    return [
        {
            "identity_ref": identity_ref(identity),
            "source_seed_id": identity.source_seed_id,
            "source_seed_name": identity.source_seed_name,
            "category": identity.category.value,
            "dimension_type": identity.dimension_type,
            "value": identity.value,
            "affinity_tags": identity.affinity_tags,
            "priority": identity.priority,
            "confidence": identity.confidence,
            "merchandise_relevance": identity.merchandise_relevance,
        }
        for identity in identities
    ]


def life_shape(identity: ExpandedIdentity) -> str:
    """Classify one identity as a life the collision scorer can pair."""

    text = " ".join(
        [identity.value, identity.dimension_type, identity.source_seed_name, *identity.affinity_tags]
    ).casefold()
    if any(word in text for word in ("parent", "college", "retirement", "newborn", "grief", "divorce", "moved", "relocated")):
        return "life_situation"
    if identity.category.value == "interest" or any(
        word in text for word in ("hobby", "garden", "music", "game", "dog", "plant", "bike")
    ):
        return "hobby"
    if any(word in text for word in ("community", "club", "fans", "subreddit")):
        return "community"
    if identity.category.value == "value":
        return "life_situation"
    if identity.category.value == "audience":
        return "job"
    return "identity"


def pair_kind(shapes: list[str]) -> str | None:
    """Name the cross-life pattern, if the pair is two different lives."""

    unique = set(shapes)
    if "job" in unique and "hobby" in unique:
        return "job_x_hobby"
    if "life_situation" in unique and len(unique) >= 2:
        return "identity_x_life_situation"
    if shapes.count("community") >= 2 or (len(shapes) >= 2 and shapes.count("job") >= 2):
        return "two_communities"
    if "community" in unique and len(unique) >= 2:
        return "two_communities"
    if len(unique) >= 2:
        return "two_lives"
    return None


def collision_scores(items: tuple[ExpandedIdentity, ...]) -> dict[str, int | str | list[str]]:
    """Score unexpectedness, a real person being both, and a stranger still getting it.

    Shared affinity tags lower the score. They are not a bonus for a natural pair.
    """

    tag_sets = [set(item.affinity_tags) for item in items]
    shared = sorted(set.intersection(*tag_sets)) if tag_sets else []
    shapes = [life_shape(item) for item in items]
    kind = pair_kind(shapes)
    unexpectedness = 4 if kind else 1
    unexpectedness += max(0, 3 - len(shared))
    unexpectedness -= min(4, len(shared))
    unexpectedness = max(0, unexpectedness)
    if kind in {"job_x_hobby", "identity_x_life_situation", "two_communities"}:
        real_person = 8
    elif kind == "two_lives":
        real_person = 5
    else:
        real_person = 2
    word_counts = [len(item.value.split()) for item in items]
    stranger = 6 if word_counts and all(1 <= count <= 5 for count in word_counts) else 3
    return {
        "unexpectedness": unexpectedness,
        "real_person_both": real_person,
        "stranger_gets_it": stranger,
        "collision_score": unexpectedness + real_person + stranger,
        "pair_kind": kind or "same_life",
        "life_shapes": shapes,
        "shared_tags": shared,
    }


def _candidate(
    items: tuple[ExpandedIdentity, ...],
    run_id: str,
    *,
    rationale: str | None = None,
    distinctiveness: int | None = None,
    model: str = "deterministic",
) -> IdentityIntersection:
    """Build a candidate and retain the collision score instead of a shared-tag bonus."""

    scored = collision_scores(items)
    identities = [item.value for item in items]
    source_ids = [item.source_seed_id for item in items]
    categories = [item.category.value for item in items]
    candidate_score = int(scored["collision_score"])
    if distinctiveness is not None:
        candidate_score += distinctiveness
    metadata = {
        "categories": categories,
        "shared_tags": scored["shared_tags"],
        "candidate_score": candidate_score,
        "collision_score": scored["collision_score"],
        "unexpectedness": scored["unexpectedness"],
        "real_person_both": scored["real_person_both"],
        "stranger_gets_it": scored["stranger_gets_it"],
        "pair_kind": scored["pair_kind"],
        "life_shapes": scored["life_shapes"],
        "identity_refs": [identity_ref(item) for item in items],
        "generation_method": "provider" if rationale else "deterministic",
        "model": model,
    }
    if rationale:
        metadata["composition_rationale"] = rationale
    if distinctiveness is not None:
        metadata["distinctiveness"] = distinctiveness
    return IdentityIntersection(
        run_id=run_id,
        identities=identities,
        source_seed_ids=source_ids,
        metadata=metadata,
    )


def _provider_candidate(
    proposal: IntersectionProposal,
    catalog: dict[str, ExpandedIdentity],
    run_id: str,
    *,
    model: str,
) -> IdentityIntersection:
    """Validate one provider proposal and materialize it from trusted application records."""

    refs = list(dict.fromkeys(proposal.identity_refs))
    if len(refs) != len(proposal.identity_refs):
        raise ValueError("Stage 3 provider proposal contains duplicate identity references.")
    missing_refs = [ref for ref in refs if ref not in catalog]
    if missing_refs:
        raise ValueError(f"Stage 3 provider proposal contains unknown identity refs: {missing_refs}.")

    items = tuple(catalog[ref] for ref in refs)
    kind = pair_kind([life_shape(item) for item in items])
    categories = {item.category.value for item in items}
    crosses_lives = kind in {"job_x_hobby", "identity_x_life_situation", "two_communities", "two_lives"}
    if not crosses_lives and not {"audience", "interest"}.issubset(categories):
        raise ValueError("Stage 3 provider proposal must combine two different lives.")
    if len({item.source_seed_id for item in items}) < 2:
        raise ValueError("Stage 3 provider proposal must combine at least two source seeds.")
    source_counts: dict[str, int] = {}
    for item in items:
        source_counts[item.source_seed_id] = source_counts.get(item.source_seed_id, 0) + 1
    if max(source_counts.values()) > 2:
        raise ValueError("Stage 3 provider proposal uses too many dimensions from one source seed.")

    return _candidate(
        items,
        run_id,
        rationale=proposal.composition_rationale,
        distinctiveness=proposal.distinctiveness,
        model=model,
    )


def execute(
    input_data: IntersectionGenerationInput,
    *,
    run_id: str,
    reasoning_output: Stage3ReasoningOutput | None = None,
    model: str = "deterministic",
) -> IntersectionGenerationOutput:
    """Materialize provider proposals, or generate deterministic candidates when no provider exists.

    Provider proposals are individually checked against the catalog. Invalid proposals are omitted
    rather than persisted; if none survive, raising ``ValueError`` fails the live stage so the
    provider problem remains visible to the operator.
    """

    if reasoning_output is not None:
        catalog = {identity_ref(identity): identity for identity in input_data.identities}
        candidates: list[IdentityIntersection] = []
        seen: set[str] = set()
        rejected = 0
        for proposal in reasoning_output.proposals:
            try:
                candidate = _provider_candidate(proposal, catalog, run_id, model=model)
            except ValueError:
                rejected += 1
                continue
            key = "|".join(sorted(identity_ref(catalog[ref]) for ref in proposal.identity_refs))
            if key in seen:
                rejected += 1
                continue
            seen.add(key)
            candidates.append(candidate)

        if not candidates:
            raise ValueError("Stage 3 provider returned no valid identity intersections.")
        candidates.sort(
            key=lambda candidate: (
                -int(candidate.metadata.get("candidate_score", 0)),
                candidate.intersection_id,
            )
        )
        return IntersectionGenerationOutput(
            intersections=candidates[: input_data.max_intersections * 3],
            provider_proposals_count=len(reasoning_output.proposals),
            provider_rejected_count=rejected,
            summary=reasoning_output.summary,
            model=model,
        )

    cores = [identity for identity in input_data.identities if identity.dimension_type == "core"]
    groups: dict[str, list[ExpandedIdentity]] = {}
    for identity in cores:
        groups.setdefault(identity.category, []).append(identity)
    for group in groups.values():
        group.sort(key=lambda identity: (-identity.priority, identity.value.lower()))

    candidates: list[IdentityIntersection] = []
    audiences = groups.get("audience", [])
    for audience in audiences:
        for interest in groups.get("interest", []):
            candidates.append(_candidate((audience, interest), run_id))
            for value in groups.get("value", []):
                candidates.append(_candidate((audience, interest, value), run_id))
    for index, left in enumerate(audiences):
        for right in audiences[index + 1 :]:
            if left.source_seed_id == right.source_seed_id:
                continue
            candidates.append(_candidate((left, right), run_id))

    candidates.sort(
        key=lambda candidate: (
            -int(candidate.metadata.get("candidate_score", 0)),
            "|".join(sorted(item.lower() for item in candidate.identities)),
        )
    )
    return IntersectionGenerationOutput(
        intersections=candidates[: input_data.max_intersections * 3],
    )
