"""Stage 11: optionally screen duplicate phrases before image generation.

This MVP check compares normalized phrases within the current run. It is not a semantic similarity
search, trademark search, or legal IP assessment; naming the stage as a duplicate screen keeps the
client-facing result honest while preserving a future provider insertion point.
"""

import re

from pydantic import BaseModel, Field

from merchandise_discovery.domain.models.artifacts import MerchandiseConcept
from merchandise_discovery.domain.models.common import ConceptVerdict

# Very crowded phrases are dropped. Moderately crowded phrases stay and rank lower.
DROP_COUNT = 40
DOWNRANK_COUNT = 15


class SaturationFinding(BaseModel):
    """Marketplace crowding for one concept phrase."""

    concept_id: str
    count: int | None = None
    source: str = "skipped"
    note: str = ""


class SimilarityCheckInput(BaseModel):
    """Critiqued concepts entering the optional duplicate and saturation screen."""

    concepts: list[MerchandiseConcept]
    saturation: list[SaturationFinding] = Field(default_factory=list)


class SimilarityCheck(BaseModel):
    """Duplicate-screen result for one concept."""

    concept_id: str
    risk_level: str
    similar_to: str | None = None
    reason: str


class SimilarityCheckOutput(BaseModel):
    """All concepts and their optional-screen outcomes."""

    concepts: list[MerchandiseConcept]
    survivors: list[MerchandiseConcept]
    rejected: list[MerchandiseConcept]
    checks: list[SimilarityCheck]


def _normalized_phrase(phrase: str) -> str:
    """Normalize case, punctuation, and repeated whitespace for exact duplicate detection."""

    without_punctuation = re.sub(r"[^\w\s]+", " ", phrase.casefold(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", without_punctuation).strip()


def execute(input_data: SimilarityCheckInput) -> SimilarityCheckOutput:
    """Reject later duplicate phrases globally within this run, keeping the highest score."""

    seen: dict[str, MerchandiseConcept] = {}
    survivors: list[MerchandiseConcept] = []
    rejected: list[MerchandiseConcept] = []
    checks: list[SimilarityCheck] = []
    for concept in sorted(
        input_data.concepts,
        key=lambda item: (-(item.overall_score or 0), item.concept_id),
    ):
        key = _normalized_phrase(concept.phrase)
        original = seen.get(key)
        if original is None:
            seen[key] = concept
            survivors.append(concept)
            checks.append(
                SimilarityCheck(
                    concept_id=concept.concept_id,
                    risk_level="low",
                    reason="No duplicate phrase was found in the current run.",
                )
            )
            continue
        reason = f"Duplicate phrase detected; retained higher-scoring concept {original.concept_id}."
        rejected_concept = concept.model_copy(
            update={
                "verdict": ConceptVerdict.REJECT,
                "selected": False,
                "critique": {**concept.critique, "similarity_reason": reason},
            }
        )
        rejected.append(rejected_concept)
        checks.append(
            SimilarityCheck(
                concept_id=concept.concept_id,
                risk_level="high",
                similar_to=original.concept_id,
                reason=reason,
            )
        )
    survivors, rejected, checks = _apply_saturation(
        survivors,
        rejected,
        checks,
        input_data.saturation,
    )
    concepts = survivors + rejected
    return SimilarityCheckOutput(
        concepts=concepts,
        survivors=survivors,
        rejected=rejected,
        checks=checks,
    )


def _apply_saturation(
    survivors: list[MerchandiseConcept],
    rejected: list[MerchandiseConcept],
    checks: list[SimilarityCheck],
    findings: list[SaturationFinding],
) -> tuple[list[MerchandiseConcept], list[MerchandiseConcept], list[SimilarityCheck]]:
    """Drop very crowded phrases and down-rank the moderately crowded ones.

    A skipped finding leaves the concept alone. If every survivor would be dropped,
    the least crowded one stays so ranking still has a line to consider.
    """

    by_id = {finding.concept_id: finding for finding in findings}
    if not by_id:
        return survivors, rejected, checks
    kept: list[MerchandiseConcept] = []
    crowded: list[tuple[int, MerchandiseConcept, SaturationFinding]] = []
    updated_checks = list(checks)
    for concept in survivors:
        finding = by_id.get(concept.concept_id)
        if finding is None or finding.count is None:
            kept.append(concept)
            continue
        if finding.count >= DROP_COUNT:
            crowded.append((finding.count, concept, finding))
            continue
        if finding.count >= DOWNRANK_COUNT:
            lowered = max(0.0, (concept.overall_score or 5.0) - 2.0)
            kept.append(
                concept.model_copy(
                    update={
                        "overall_score": lowered,
                        "critique": {**concept.critique, "saturation_note": finding.note},
                    }
                )
            )
            updated_checks.append(
                SimilarityCheck(
                    concept_id=concept.concept_id,
                    risk_level="medium",
                    reason=finding.note,
                )
            )
            continue
        kept.append(concept)
    if not kept and crowded:
        crowded.sort(key=lambda item: item[0])
        _count, concept, finding = crowded.pop(0)
        kept.append(
            concept.model_copy(
                update={"critique": {**concept.critique, "saturation_note": finding.note}}
            )
        )
    for _count, concept, finding in crowded:
        reason = finding.note or "Phrase is already crowded in sticker listings."
        rejected.append(
            concept.model_copy(
                update={
                    "verdict": ConceptVerdict.REJECT,
                    "selected": False,
                    "critique": {**concept.critique, "saturation_note": reason},
                }
            )
        )
        updated_checks.append(
            SimilarityCheck(
                concept_id=concept.concept_id,
                risk_level="high",
                reason=reason,
            )
        )
    return kept, rejected, updated_checks
