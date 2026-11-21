"""OpenAI strict mode rejects objects that allow extra properties or omit required."""

from openai.lib._pydantic import to_strict_json_schema

from merchandise_discovery.domain.humor import HumorCritiqueBatch, NichePairBatch
from merchandise_discovery.domain.humor_playbook import HumorPlaybook
from merchandise_discovery.domain.pipelines.social_behavior_identity.pipeline import (
    BehaviorIdentityOutput,
)
from merchandise_discovery.domain.pipelines.social_behavior_text.pipeline import (
    SocialBehaviorTextOutput,
)
from merchandise_discovery.domain.pipelines.social_identity_focused.pipeline import (
    SocialIdentityTextOutput,
)
from merchandise_discovery.domain.stages.stage_01_seed_discovery import Stage1ReasoningOutput
from merchandise_discovery.domain.stages.stage_02_identity_expansion import Stage2ReasoningOutput
from merchandise_discovery.domain.stages.stage_03_intersection_generation import (
    Stage3ReasoningOutput,
)
from merchandise_discovery.domain.stages.stage_04_coherence_hypothesis import Stage4ReasoningOutput
from merchandise_discovery.domain.stages.stage_06_compact_research_development import (
    CompactReasoningOutput,
)
from merchandise_discovery.domain.stages.stage_07_experience_mining import Stage7ReasoningOutput
from merchandise_discovery.domain.stages.stage_08_opportunity_scoring import Stage8ReasoningOutput
from merchandise_discovery.domain.stages.stage_09_concept_generation import Stage9ReasoningOutput
from merchandise_discovery.domain.stages.stage_10_concept_critique import Stage10ReasoningOutput
from merchandise_discovery.domain.stages.stage_12_final_selection import Stage12ReasoningOutput
from merchandise_discovery.domain.stages.stage_13_design_brief import Stage13ReasoningOutput
from merchandise_discovery.domain.stages.stage_16_artwork_critique import ArtworkCritiqueProposal

RESPONSE_MODELS = (
    SocialIdentityTextOutput,
    SocialBehaviorTextOutput,
    BehaviorIdentityOutput,
    HumorCritiqueBatch,
    NichePairBatch,
    HumorPlaybook,
    Stage1ReasoningOutput,
    Stage2ReasoningOutput,
    Stage3ReasoningOutput,
    Stage4ReasoningOutput,
    CompactReasoningOutput,
    Stage7ReasoningOutput,
    Stage8ReasoningOutput,
    Stage9ReasoningOutput,
    Stage10ReasoningOutput,
    Stage12ReasoningOutput,
    Stage13ReasoningOutput,
    ArtworkCritiqueProposal,
)


def _strict_issues(schema: object, path: str = "") -> list[str]:
    """Return strict-mode violations. Objects must forbid extra keys and require every property."""

    issues: list[str] = []
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            if schema.get("additionalProperties") is not False:
                issues.append(f"{path or '<root>'}: additionalProperties must be false")
            properties = schema.get("properties")
            if isinstance(properties, dict):
                required = schema.get("required")
                if not isinstance(required, list) or set(required) != set(properties):
                    issues.append(f"{path or '<root>'}: required must list every property")
        for key, value in schema.items():
            if key == "additionalProperties" and not isinstance(value, dict):
                continue
            issues.extend(_strict_issues(value, f"{path}.{key}" if path else key))
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            issues.extend(_strict_issues(value, f"{path}[{index}]"))
    return issues


def test_every_response_format_schema_is_strict() -> None:
    """Critic, niche-pair, playbook, and every live response model satisfy OpenAI strict mode."""

    assert {model.__name__ for model in RESPONSE_MODELS} >= {
        "HumorCritiqueBatch",
        "NichePairBatch",
        "HumorPlaybook",
        "SocialIdentityTextOutput",
    }
    failures: list[str] = []
    for model in RESPONSE_MODELS:
        issues = _strict_issues(to_strict_json_schema(model))
        if issues:
            failures.append(f"{model.__name__}: " + "; ".join(issues))
    assert not failures
