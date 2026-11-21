"""Executor for discovery stages and optional provider-backed reasoning.

The executor owns orchestration concerns: loading prior stage outputs, supplying repositories and
providers to stage functions, and persisting artifact snapshots. Each stage module remains
independently portable and provider dependencies are injected here.
"""

import json
import logging

from merchandise_discovery.application.stage_executor import StageNotImplementedError, StageResult
from merchandise_discovery.domain.humor import (
    HumorCritiqueBatch,
    LineReview,
    apply_line_critic,
)
from merchandise_discovery.domain.humor_references import (
    copied_from_source,
    humor_reference_prompt,
    is_too_similar_to_references,
    select_humor_references,
)
from merchandise_discovery.domain.models.common import PipelineVariant, SocialSource, StageStatus
from merchandise_discovery.domain.models.usage import UsageMetrics, combine_usage
from merchandise_discovery.domain.models.workflow import StageExecution, WorkflowRun
from merchandise_discovery.domain.pipelines.social_behavior_identity import (
    pipeline as social_behavior_identity,
)
from merchandise_discovery.domain.pipelines.social_behavior_text import artwork as social_artwork
from merchandise_discovery.domain.pipelines.social_behavior_text import pipeline as social_behavior
from merchandise_discovery.domain.pipelines.social_identity_focused import (
    artwork as social_identity_artwork,
)
from merchandise_discovery.domain.pipelines.social_identity_focused import (
    pipeline as social_identity,
)
from merchandise_discovery.domain.pipelines.social_identity_v2 import (
    artwork as social_identity_v2_artwork,
)
from merchandise_discovery.domain.pipelines.social_identity_v2 import (
    pipeline as social_identity_v2,
)
from merchandise_discovery.domain.stages import stage_01_seed_discovery as stage_01
from merchandise_discovery.domain.stages import stage_02_identity_expansion as stage_02
from merchandise_discovery.domain.stages import stage_03_intersection_generation as stage_03
from merchandise_discovery.domain.stages import stage_04_coherence_hypothesis as stage_04
from merchandise_discovery.domain.stages import stage_05_pre_research_filter as stage_05
from merchandise_discovery.domain.stages import (
    stage_06_compact_research_development as stage_06_compact,
)
from merchandise_discovery.domain.stages import stage_06_niche_research as stage_06
from merchandise_discovery.domain.stages import stage_07_experience_mining as stage_07
from merchandise_discovery.domain.stages import stage_08_opportunity_scoring as stage_08
from merchandise_discovery.domain.stages import stage_09_compact_artwork_gallery as stage_09_gallery
from merchandise_discovery.domain.stages import stage_09_concept_generation as stage_09
from merchandise_discovery.domain.stages import stage_10_concept_critique as stage_10
from merchandise_discovery.domain.stages import stage_11_similarity_ip_check as stage_11
from merchandise_discovery.domain.stages import stage_12_final_selection as stage_12
from merchandise_discovery.domain.stages import stage_13_design_brief as stage_13
from merchandise_discovery.domain.stages import stage_14_prompt_compilation as stage_14
from merchandise_discovery.domain.stages import stage_15_artwork_generation as stage_15
from merchandise_discovery.domain.stages import stage_16_artwork_critique as stage_16
from merchandise_discovery.domain.stages import stage_17_artwork_revision as stage_17
from merchandise_discovery.infrastructure.mongo.repositories.artwork_repository import (
    ArtworkRepository,
)
from merchandise_discovery.infrastructure.mongo.repositories.brief_repository import BriefRepository
from merchandise_discovery.infrastructure.mongo.repositories.concept_repository import (
    ConceptRepository,
)
from merchandise_discovery.infrastructure.mongo.repositories.evidence_repository import (
    EvidenceRepository,
)
from merchandise_discovery.infrastructure.mongo.repositories.intersection_repository import (
    IntersectionRepository,
)
from merchandise_discovery.infrastructure.mongo.repositories.niche_repository import NicheRepository
from merchandise_discovery.infrastructure.mongo.repositories.run_repository import RunRepository
from merchandise_discovery.infrastructure.mongo.repositories.seed_repository import SeedRepository
from merchandise_discovery.infrastructure.mongo.repositories.stage_execution_repository import (
    StageExecutionRepository,
)
from merchandise_discovery.infrastructure.providers.image_provider import ImageProvider
from merchandise_discovery.infrastructure.providers.reasoning_provider import ReasoningProvider
from merchandise_discovery.infrastructure.providers.research_provider import ResearchProvider
from merchandise_discovery.infrastructure.storage import ArtworkStorage

logger = logging.getLogger(__name__)


def _saturation_findings(checker, items: list[tuple[str, str]]) -> list:
    """Adapt marketplace findings to the stage 11 record."""

    return [
        stage_11.SaturationFinding(
            concept_id=finding.item_id,
            count=finding.count,
            source=finding.source,
            note=finding.note,
        )
        for finding in checker.check(items)
    ]


def _social_artwork_candidates(run: WorkflowRun, candidates: list) -> list:
    """Return every Stage 1 candidate, or the subset explicitly approved for artwork."""

    if not run.config.social_manual_artwork_selection:
        return candidates
    selected_indices = run.config.social_selected_candidate_indices
    if not selected_indices:
        raise ValueError("Manual artwork selection has no persisted candidate choices.")
    if any(index < 0 or index >= len(candidates) for index in selected_indices):
        raise ValueError("Manual artwork selection no longer matches the Stage 1 candidates.")
    return [candidates[index] for index in selected_indices]


class DiscoveryStageExecutor:
    """Load, run, and persist automated stages without coupling domain code to MongoDB."""

    def __init__(
        self,
        seed_repository: SeedRepository,
        intersection_repository: IntersectionRepository,
        stage_repository: StageExecutionRepository,
        niche_repository: NicheRepository,
        evidence_repository: EvidenceRepository,
        research_provider: ResearchProvider,
        concept_repository: ConceptRepository,
        brief_repository: BriefRepository,
        artwork_repository: ArtworkRepository,
        image_provider: ImageProvider,
        reasoning_provider: ReasoningProvider | None = None,
        artwork_storage: ArtworkStorage | None = None,
        openai_image_detail: str = "high",
        run_repository: RunRepository | None = None,
        saturation_checker=None,
        reddit_reader=None,
        humor_reference_loader=None,
    ):
        self._seeds = seed_repository
        self._intersections = intersection_repository
        self._stage_repository = stage_repository
        self._niches = niche_repository
        self._evidence = evidence_repository
        self._research_provider = research_provider
        self._concepts = concept_repository
        self._briefs = brief_repository
        self._artworks = artwork_repository
        self._image_provider = image_provider
        self._artwork_storage = artwork_storage
        self._reasoning_provider = reasoning_provider
        self._openai_image_detail = openai_image_detail
        self._runs = run_repository
        self._saturation_checker = saturation_checker
        self._reddit_reader = reddit_reader
        self._humor_reference_loader = humor_reference_loader

    def _recent_identity_selections(self, run: WorkflowRun, limit: int = 12) -> list[str]:
        """Return bounded identity history for diversity-aware auto-selection prompts.

        Recent identity context is assembled in the application layer from repositories and passed
        into the pipeline input. This keeps prompt builders pure and avoids making domain code
        reach directly into MongoDB. Missing repository context is valid for isolated tests and
        fixture callers, so those paths simply receive an empty history.
        """

        if self._runs is None:
            return []
        identities: list[str] = []
        seen: set[str] = set()
        for previous_run in self._runs.list_recent(limit=40):
            if previous_run.run_id == run.run_id:
                continue
            if previous_run.config.pipeline_variant not in {
                PipelineVariant.SOCIAL_IDENTITY_FOCUSED,
                PipelineVariant.SOCIAL_IDENTITY_V2,
            }:
                continue
            if not previous_run.config.social_auto_identity:
                continue
            previous_stage = self._stage_repository.get_latest(previous_run.run_id, 1)
            if previous_stage is None or previous_stage.status != StageStatus.COMPLETED:
                continue
            output = previous_stage.output_data or {}
            identity = str(output.get("identity_selected") or "").strip()
            identity_key = identity.casefold()
            if identity and identity_key not in seen:
                identities.append(identity)
                seen.add(identity_key)
            if len(identities) >= limit:
                break
        return identities

    def _finish_social_text(self, run: WorkflowRun, input_model, pipeline_module, output_model):
        """Validate the drafted lines, then record which humor references the run used."""

        reasoning_output, usage, selection, line_reviews = self._social_reasoning(
            run,
            input_model,
            pipeline_module,
            output_model,
        )
        output = pipeline_module.execute(
            input_model,
            reasoning_output=reasoning_output,
            model=usage.model if usage.provider != "fixture" else "deterministic",
        )
        output = self._stamp_humor_context(output, selection)
        pair_update = {"line_reviews": line_reviews}
        user_a = str(getattr(input_model, "niche_a", "") or "").strip()
        user_b = str(getattr(input_model, "niche_b", "") or "").strip()
        if user_a and user_b:
            pair_update["niche_pair_a"] = user_a
            pair_update["niche_pair_b"] = user_b
        return output.model_copy(update=pair_update), usage

    def _social_reasoning(self, run: WorkflowRun, input_model, pipeline_module, output_model):
        """Collect comments, draft joke-shaped lines, then let a critic cut them."""

        selection = self._humor_selection(run, input_model)
        reference_block = humor_reference_prompt(selection)
        if self._reasoning_provider is None:
            return None, UsageMetrics(), selection, []
        quotes = self._collect_reddit_quotes(input_model)
        draft_count = min(25, max(input_model.candidate_count, input_model.candidate_count * 3))
        domains = None
        if not quotes:
            domains = tuple(
                "reddit.com" if source.value == "reddit" else "x.com" for source in input_model.sources
            )
        user_prompt = pipeline_module.build_user_prompt(
            input_model,
            draft_count=draft_count,
            quotes=quotes,
            humor_reference_block=reference_block,
        )
        response = self._reasoning_provider.complete_structured(
            system_prompt=pipeline_module.reasoning_instructions(run.config.humor_tone),
            user_prompt=user_prompt,
            response_model=output_model,
            web_search_domains=domains,
        )
        usage = response.usage
        candidates, reviews = self._drop_unoriginal(
            list(getattr(response.output, "candidates", [])),
            selection.examples,
        )
        if candidates:
            candidates, critic_usage, critic_rows = self._critic_pass(
                run,
                candidates,
                input_model.candidate_count,
                reference_block,
            )
            usage = combine_usage(usage, critic_usage)
            reviews.extend(critic_rows)
        chosen = response.output
        short = len(candidates) < input_model.candidate_count
        weak_pair = self._pair_is_weak(chosen, input_model)
        if short or weak_pair:
            reasons = []
            if short:
                reasons.append(
                    "too few lines survived. Dropped lines copied the source, copied a "
                    "reference, or scored under 7 on 'would this get upvoted on Reddit'"
                )
            if weak_pair:
                reasons.append(
                    "niche_pair_a and niche_pair_b were missing, identical, or pairing_score "
                    "was under 7. Choose two niches whose audiences share a life and score "
                    "that pairing at 7 or higher"
                )
            retry = self._reasoning_provider.complete_structured(
                system_prompt=pipeline_module.reasoning_instructions(run.config.humor_tone),
                user_prompt=(
                    f"{user_prompt}\nRewrite. {'. '.join(reasons)}. "
                    "artwork_text must be an original joke, never the source sentence or a "
                    "close paraphrase."
                ),
                response_model=output_model,
                web_search_domains=domains,
            )
            usage = combine_usage(usage, retry.usage)
            retried, retry_reviews = self._drop_unoriginal(
                list(getattr(retry.output, "candidates", [])),
                selection.examples,
            )
            if retried:
                retried, critic_usage, critic_rows = self._critic_pass(
                    run,
                    retried,
                    input_model.candidate_count,
                    reference_block,
                )
                usage = combine_usage(usage, critic_usage)
                retry_reviews.extend(critic_rows)
            if len(retried) >= len(candidates):
                candidates = retried
                chosen = retry.output
                reviews = retry_reviews
            elif self._pair_rank(retry.output) > self._pair_rank(chosen):
                chosen = chosen.model_copy(
                    update={
                        "niche_pair_a": retry.output.niche_pair_a,
                        "niche_pair_b": retry.output.niche_pair_b,
                        "pairing_score": retry.output.pairing_score,
                        "pairing_reason": retry.output.pairing_reason,
                    }
                )
        if not candidates:
            raise RuntimeError(
                "Every line was dropped. Each one copied its source, copied a reference joke, "
                "or scored under 7 on 'would this get upvoted on Reddit'."
            )
        output = chosen.model_copy(
            update={"candidates": candidates[: input_model.candidate_count]}
        )
        output = self._drop_crowded_lines(output)
        return output, usage, selection, reviews

    def _collect_reddit_quotes(self, input_model) -> list:
        """Pull top comments when Reddit is selected. A failure leaves the writer on web search."""

        if self._reddit_reader is None or SocialSource.REDDIT not in input_model.sources:
            return []
        parts = [
            getattr(input_model, "niche_a", ""),
            getattr(input_model, "niche_b", ""),
            getattr(input_model, "identity", ""),
            getattr(input_model, "query", ""),
        ]
        query = " ".join(str(part).strip() for part in parts if str(part).strip())
        if len(query) < 3:
            query = "everyday frustration"
        try:
            return self._reddit_reader.collect(query)
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            logger.warning("Reddit comment collection skipped: %s", error)
            return []

    def _humor_selection(self, run: WorkflowRun, input_model):
        """Load references for this run only. The loader itself does not cache."""

        from merchandise_discovery.domain.humor_references import HumorReferenceSelection

        if self._humor_reference_loader is None:
            return HumorReferenceSelection(examples=[], themes=[])
        try:
            references = self._humor_reference_loader() or []
        except Exception as error:  # noqa: BLE001 - references are optional context.
            logger.warning("Humor references were not loaded (%s).", type(error).__name__)
            references = []
        niches = [
            str(getattr(input_model, "niche_a", "") or ""),
            str(getattr(input_model, "niche_b", "") or ""),
            str(getattr(input_model, "identity", "") or ""),
        ]
        return select_humor_references(references, tone=run.config.humor_tone, niches=niches)

    def _pair_is_weak(self, output, input_model) -> bool:
        """A user-supplied pair is trusted. An AI pair must name two lives and score at least 7."""

        user_a = str(getattr(input_model, "niche_a", "") or "").strip()
        user_b = str(getattr(input_model, "niche_b", "") or "").strip()
        if user_a and user_b:
            return False
        return self._pair_rank(output) < (1, 7)

    def _pair_rank(self, output) -> tuple[int, float]:
        """Rank a returned pair so a real overlap outranks a missing or low score."""

        first = str(getattr(output, "niche_pair_a", "") or "").strip()
        second = str(getattr(output, "niche_pair_b", "") or "").strip()
        distinct = bool(first and second and first.casefold() != second.casefold())
        score = getattr(output, "pairing_score", None)
        return (1 if distinct else 0, float(score) if score is not None else 0.0)

    def _drop_unoriginal(self, candidates: list, examples: list) -> tuple[list, list]:
        """Drop lines that quote the source or an upvoted reference instead of joking."""

        kept: list = []
        dropped: list = []
        for candidate in candidates:
            text = str(getattr(candidate, "artwork_text", "") or "")
            if copied_from_source(
                text,
                str(getattr(candidate, "source_quote", "") or ""),
                str(getattr(candidate, "source_excerpt", "") or ""),
            ):
                dropped.append(
                    {
                        "artwork_text": text,
                        "funny_score": None,
                        "kept": False,
                        "reason": "copied source",
                    }
                )
                continue
            if is_too_similar_to_references(text, examples):
                dropped.append(
                    {
                        "artwork_text": text,
                        "funny_score": None,
                        "kept": False,
                        "reason": "copied reference",
                    }
                )
                continue
            kept.append(candidate)
        return kept, dropped

    def _stamp_humor_context(self, output, selection):
        """Record the top examples and themes that this run's copy was judged against."""

        return output.model_copy(
            update={
                "humor_examples_used": [
                    {
                        "text": item.text,
                        "upvotes": item.upvotes,
                        "humor_type": item.humor_type,
                        "niche": item.niche,
                        "subreddit": item.subreddit,
                        "post_url": item.post_url,
                    }
                    for item in selection.display_examples
                ],
                "humor_themes_used": [item.text for item in selection.themes[:10]],
            }
        )

    def _critic_pass(
        self,
        run: WorkflowRun,
        candidates: list,
        keep_count: int,
        reference_block: str = "",
    ):
        """Score humor against the reference set and drop lines under the upvote bar."""

        numbered = "\n".join(
            f"{index}. {getattr(candidate, 'artwork_text', '')} "
            f"(mechanism: {getattr(candidate, 'humor_mechanism', '')}; "
            f"detail: {getattr(candidate, 'concrete_detail', '')})"
            for index, candidate in enumerate(candidates)
        )
        response = self._reasoning_provider.complete_structured(
            system_prompt=(
                "You are a merchandise humor critic. Score each drafted sticker line. "
                "humor_landed, novelty, and tone_match are 0 to 10. giftability is 0 to 10 "
                "but must not decide the cut when the tone is dark. reddit_upvote_score is "
                "1 to 10 for 'would this get upvoted on Reddit' compared with the reference "
                "jokes. Score title puns and clever names at 4 or below. Score a real setup "
                "and turn, confession, or deadpan absurdity at 7 or above only when it would "
                "actually get a laugh. Score a line that quotes or closely paraphrases its "
                "source at 4 or below. Do not reward a line that copies a reference."
            ),
            user_prompt=(
                f"Requested tone: {run.config.humor_tone.value}.\n"
                f"{reference_block}"
                f"Score every index. Lines under 7 on reddit_upvote_score will be dropped.\n"
                f"{numbered}"
            ),
            response_model=HumorCritiqueBatch,
        )
        reviews = [
            LineReview(
                index=review.index,
                humor_landed=review.humor_landed,
                novelty=review.novelty,
                tone_match=review.tone_match,
                giftability=review.giftability,
                reddit_upvote_score=review.reddit_upvote_score,
            )
            for review in response.output.reviews
        ]
        scored = []
        by_index = {review.index: review for review in reviews}
        for index, candidate in enumerate(candidates):
            review = by_index.get(index)
            score = review.reddit_upvote_score if review is not None else None
            if score is None or not hasattr(candidate, "model_copy"):
                scored.append(candidate)
                continue
            scored.append(candidate.model_copy(update={"funny_score": score}))
        kept = apply_line_critic(
            scored,
            reviews,
            keep_count=keep_count,
            tone=run.config.humor_tone,
        )
        kept_ids = {id(item) for item in kept}
        rows = []
        for index, candidate in enumerate(scored):
            review = by_index.get(index)
            score = review.reddit_upvote_score if review is not None else None
            if id(candidate) in kept_ids:
                reason, kept_flag = "kept", True
            elif score is not None and score < 7:
                reason, kept_flag = "below 7", False
            else:
                reason, kept_flag = "cut by critic", False
            rows.append(
                {
                    "artwork_text": str(getattr(candidate, "artwork_text", "") or ""),
                    "funny_score": score,
                    "kept": kept_flag,
                    "reason": reason,
                }
            )
        return kept, response.usage, rows

    def _drop_crowded_lines(self, output):
        """Remove sticker lines that already have a crowded marketplace, when a check is configured."""

        if self._saturation_checker is None or not getattr(output, "candidates", None):
            return output
        findings = {
            finding.item_id: finding
            for finding in self._saturation_checker.check(
                [
                    (str(index), candidate.artwork_text)
                    for index, candidate in enumerate(output.candidates)
                ]
            )
        }
        kept = []
        dropped = []
        for index, candidate in enumerate(output.candidates):
            finding = findings.get(str(index))
            if finding is not None and finding.drop:
                dropped.append((finding.count or 0, candidate))
                continue
            kept.append(candidate)
        if not kept and dropped:
            dropped.sort(key=lambda item: item[0])
            kept = [dropped[0][1]]
        if not kept:
            return output
        return output.model_copy(update={"candidates": kept})

    def _reason(
        self,
        stage_name: str,
        input_data: dict,
        response_model,
        instructions: str | None = None,
    ):
        """Call structured reasoning while keeping prompts and SDK details outside stage modules."""

        if self._reasoning_provider is None:
            return None, UsageMetrics()
        user_prompt = (
            f"Execute {stage_name}. Validate the following stage input and produce the requested "
            f"Pydantic output. Input JSON:\n{json.dumps(input_data, default=str)}"
        )
        if instructions:
            user_prompt = f"{instructions}\n\n{user_prompt}"
        response = self._reasoning_provider.complete_structured(
            system_prompt=(
                "You are a merchandise discovery specialist. Return only the requested structured "
                "output, preserve supplied IDs, do not invent citations, and keep recommendations "
                "specific to the observed audience experience."
            ),
            user_prompt=user_prompt,
            response_model=response_model,
        )
        return response.output, response.usage

    def _critique_artworks(
        self,
        input_model: stage_16.ArtworkCritiqueInput,
    ) -> tuple[stage_16.ArtworkCritiqueOutput, UsageMetrics]:
        """Run one structured Luna vision request per artwork and materialize the review set.

        One request per image keeps usage and failures attributable to a specific candidate. The
        provider receives the original prompt and combination name alongside the image so it can
        judge audience recognition rather than generic visual polish.
        """

        if self._reasoning_provider is None or not input_model.artworks:
            return stage_16.execute(input_model), UsageMetrics()

        proposals: list[stage_16.ArtworkCritiqueProposal] = []
        usages: list[UsageMetrics] = []
        for artwork in input_model.artworks:
            if not artwork.source_url:
                raise ValueError(
                    f"Artwork {artwork.artwork_id} has no public source URL for Luna review."
                )
            response = self._reasoning_provider.complete_structured(
                system_prompt=(
                    "You are Luna, a strict merchandise artwork reviewer. Return only the supplied "
                    "structured output. The image must be judged against the specific audience and "
                    "lived-experience combination, not a broad category. Preserve the artwork_id "
                    "exactly and do not invent audience facts."
                ),
                user_prompt=(
                    f"{stage_16.reasoning_instructions()}\n\n"
                    f"Artwork ID: {artwork.artwork_id}\n"
                    f"Audience/interest/value combination: {artwork.combination_name or 'not supplied'}\n"
                    f"Original generation prompt:\n{artwork.prompt}"
                ),
                response_model=stage_16.ArtworkCritiqueProposal,
                image_url=artwork.source_url,
                image_detail=self._openai_image_detail,
                temperature=0.0,
            )
            proposal = response.output
            if proposal.artwork_id != artwork.artwork_id:
                raise ValueError(
                    f"Luna returned artwork ID {proposal.artwork_id!r}; expected {artwork.artwork_id!r}."
                )
            proposals.append(proposal)
            usages.append(response.usage)

        usage = combine_usage(*usages)
        return (
            stage_16.execute(
                input_model,
                reasoning_outputs=proposals,
                model=usage.model,
            ),
            usage,
        )

    def prepare(self, run: WorkflowRun, stage: StageExecution) -> dict:
        """Build a serializable input payload from run configuration and prior stage output."""

        if run.config.pipeline_variant == PipelineVariant.SOCIAL_IDENTITY_V2:
            if stage.stage_number == 1:
                if not run.config.social_auto_identity and run.config.social_identity_type is None:
                    raise ValueError("Identity V2 pipeline requires an identity type.")
                return social_identity_v2.SocialIdentityV2Input(
                    sources=run.config.social_sources,
                    identity=run.config.social_identity,
                    identity_type=run.config.social_identity_type,
                    auto_identity=run.config.social_auto_identity,
                    query=run.config.social_query,
                    auto_topic=run.config.social_auto_topic,
                    candidate_count=run.config.social_candidate_count,
                    niche_a=run.config.social_niche_a,
                    niche_b=run.config.social_niche_b,
                    humor_tone=run.config.humor_tone,
                    recent_identity_selections=self._recent_identity_selections(run),
                ).model_dump(mode="python")
            if stage.stage_number == 2:
                previous = self._stage_repository.get_latest(run.run_id, 1)
                if previous is None or not previous.output_data:
                    raise ValueError("Identity V2 Stage 2 is missing Stage 1 behavior output.")
                prior = social_identity_v2.SocialIdentityV2Output.model_validate(
                    previous.output_data
                )
                return social_identity_v2_artwork.IdentityV2ArtworkInput(
                    candidates=_social_artwork_candidates(run, prior.candidates),
                    artwork_variants_per_candidate=1,
                    niche_a=run.config.social_niche_a,
                    niche_b=run.config.social_niche_b,
                ).model_dump(mode="python")
            raise StageNotImplementedError(
                f"Identity V2 pipeline does not define Stage {stage.stage_number}."
            )

        if run.config.pipeline_variant == PipelineVariant.SOCIAL_BEHAVIOR_IDENTITY:
            if stage.stage_number == 1:
                return social_behavior_identity.BehaviorIdentityInput(
                    sources=run.config.social_sources,
                    query=run.config.social_query,
                    auto_topic=run.config.social_auto_topic,
                    candidate_count=run.config.social_candidate_count,
                    niche_a=run.config.social_niche_a,
                    niche_b=run.config.social_niche_b,
                    humor_tone=run.config.humor_tone,
                ).model_dump(mode="python")
            if stage.stage_number == 2:
                previous = self._stage_repository.get_latest(run.run_id, 1)
                if previous is None or not previous.output_data:
                    raise ValueError("Behavior-first identity Stage 2 is missing Stage 1 output.")
                prior = social_behavior_identity.BehaviorIdentityOutput.model_validate(
                    previous.output_data
                )
                return social_artwork.SocialArtworkInput(
                    candidates=_social_artwork_candidates(run, prior.candidates),
                    artwork_variants_per_candidate=1,
                    niche_a=run.config.social_niche_a,
                    niche_b=run.config.social_niche_b,
                ).model_dump(mode="python")
            raise StageNotImplementedError(
                f"Behavior-first identity pipeline does not define Stage {stage.stage_number}."
            )

        if run.config.pipeline_variant == PipelineVariant.SOCIAL_IDENTITY_FOCUSED:
            if stage.stage_number == 1:
                if not run.config.social_auto_identity and run.config.social_identity_type is None:
                    raise ValueError("Identity-focused pipeline requires an identity type.")
                return social_identity.SocialIdentityTextInput(
                    sources=run.config.social_sources,
                    identity=run.config.social_identity,
                    identity_type=run.config.social_identity_type,
                    auto_identity=run.config.social_auto_identity,
                    query=run.config.social_query,
                    auto_topic=run.config.social_auto_topic,
                    candidate_count=run.config.social_candidate_count,
                    niche_a=run.config.social_niche_a,
                    niche_b=run.config.social_niche_b,
                    humor_tone=run.config.humor_tone,
                    recent_identity_selections=self._recent_identity_selections(run),
                ).model_dump(mode="python")
            if stage.stage_number == 2:
                previous = self._stage_repository.get_latest(run.run_id, 1)
                if previous is None or not previous.output_data:
                    raise ValueError("Identity-focused Stage 2 is missing Stage 1 behavior output.")
                prior = social_identity.SocialIdentityTextOutput.model_validate(
                    previous.output_data
                )
                return social_identity_artwork.IdentityArtworkInput(
                    candidates=_social_artwork_candidates(run, prior.candidates),
                    artwork_variants_per_candidate=1,
                    niche_a=run.config.social_niche_a,
                    niche_b=run.config.social_niche_b,
                ).model_dump(mode="python")
            raise StageNotImplementedError(
                f"Identity-focused social pipeline does not define Stage {stage.stage_number}."
            )

        if run.config.pipeline_variant == PipelineVariant.SOCIAL_BEHAVIOR_TEXT:
            if stage.stage_number == 1:
                return social_behavior.SocialBehaviorTextInput(
                    sources=run.config.social_sources,
                    query=run.config.social_query,
                    auto_topic=run.config.social_auto_topic,
                    candidate_count=run.config.social_candidate_count,
                    niche_a=run.config.social_niche_a,
                    niche_b=run.config.social_niche_b,
                    humor_tone=run.config.humor_tone,
                ).model_dump(mode="python")
            if stage.stage_number == 2:
                previous = self._stage_repository.get_latest(run.run_id, 1)
                if previous is None or not previous.output_data:
                    raise ValueError("Social Stage 2 is missing Stage 1 behavior output.")
                prior = social_behavior.SocialBehaviorTextOutput.model_validate(
                    previous.output_data
                )
                return social_artwork.SocialArtworkInput(
                    candidates=_social_artwork_candidates(run, prior.candidates),
                    artwork_variants_per_candidate=1,
                    niche_a=run.config.social_niche_a,
                    niche_b=run.config.social_niche_b,
                ).model_dump(mode="python")
            else:
                raise StageNotImplementedError(
                    f"Social behavior pipeline does not define Stage {stage.stage_number}."
                )

        if stage.stage_number == 1:
            return stage_01.SeedDiscoveryInput(
                seed_source=run.config.seed_source,
                max_seed_items=max(6, min(12, run.config.max_intersections + 2)),
                selection_seed=run.config.selection_seed,
            ).model_dump(mode="python")

        # Compact Stage 5 was removed, but its downstream stage number remains stable for run
        # history. Stage 6 therefore reads the merged Stage 4 result directly.
        if stage.stage_number == 6 and run.config.pipeline_variant.value == "compact_research_first":
            stage_4 = self._stage_repository.get_latest(run.run_id, 4)
            if stage_4 is None or not stage_4.output_data:
                raise ValueError("Stage 6 is missing merged Stage 4 research-selection output.")
            stage_4_output = stage_04.CoherenceOutput.model_validate(stage_4.output_data)
            by_id = {item.intersection_id: item for item in stage_4_output.intersections}
            selected = [
                by_id[intersection_id]
                for intersection_id in stage_4_output.selected_intersection_ids
                if intersection_id in by_id
            ]
            if not selected:
                raise ValueError("Stage 6 has no Stage 4-selected intersections to research.")
            return stage_06_compact.CompactDevelopmentInput(
                intersections=selected,
                max_researched_niches=run.config.max_researched_niches,
                concepts_per_niche=run.config.concepts_per_niche,
                humor_tone=run.config.humor_tone.value,
            ).model_dump(mode="python")

        previous = self._stage_repository.get_latest(run.run_id, stage.stage_number - 1)
        # Stage 11 is optional. When disabled, Stage 12 consumes the Stage 10 critique output
        # and still applies the marketplace saturation check before ranking.
        stage_11_skipped = stage.stage_number == 12 and (
            previous is None
            or previous.status == StageStatus.SKIPPED
            or not previous.output_data
        )
        if stage_11_skipped:
            previous = self._stage_repository.get_latest(run.run_id, 10)
        if previous is None or not previous.output_data:
            raise ValueError(f"Stage {stage.stage_number} is missing prior stage output.")

        if stage.stage_number == 2:
            prior = stage_01.SeedDiscoveryOutput.model_validate(previous.output_data)
            return stage_02.IdentityExpansionInput(selected_seeds=prior.selected_seeds).model_dump(
                mode="python"
            )
        if stage.stage_number == 3:
            prior = stage_02.IdentityExpansionOutput.model_validate(previous.output_data)
            return stage_03.IntersectionGenerationInput(
                identities=prior.identities,
                max_intersections=run.config.max_intersections,
            ).model_dump(mode="python")
        if stage.stage_number == 4:
            prior = stage_03.IntersectionGenerationOutput.model_validate(previous.output_data)
            return stage_04.CoherenceInput(
                intersections=prior.intersections,
                max_researched_niches=run.config.max_researched_niches,
            ).model_dump(mode="python")
        if stage.stage_number == 5:
            prior = stage_04.CoherenceOutput.model_validate(previous.output_data)
            return stage_05.PreResearchFilterInput(
                intersections=prior.intersections,
                selected_intersection_ids=prior.selected_intersection_ids,
            ).model_dump(mode="python")
        if stage.stage_number == 6:
            # New runs take the AI-selected Stage 4 set directly. The Stage 5 lookup remains as a
            # compatibility fallback for historical runs created before the stages were merged.
            stage_4 = self._stage_repository.get_latest(run.run_id, 4)
            if stage_4 is not None and stage_4.output_data:
                stage_4_output = stage_04.CoherenceOutput.model_validate(stage_4.output_data)
                selected_ids = stage_4_output.selected_intersection_ids
                if selected_ids:
                    by_id = {
                        item.intersection_id: item for item in stage_4_output.intersections
                    }
                    selected = [
                        by_id[intersection_id]
                        for intersection_id in selected_ids
                        if intersection_id in by_id
                    ]
                    if run.config.pipeline_variant.value == "compact_research_first":
                        return stage_06_compact.CompactDevelopmentInput(
                            intersections=selected,
                            max_researched_niches=run.config.max_researched_niches,
                            concepts_per_niche=run.config.concepts_per_niche,
                        ).model_dump(mode="python")
                    return stage_06.NicheResearchInput(
                        intersections=selected,
                        max_researched_niches=run.config.max_researched_niches,
                    ).model_dump(mode="python")
            prior = stage_05.PreResearchFilterOutput.model_validate(previous.output_data)
            if run.config.pipeline_variant.value == "compact_research_first":
                return stage_06_compact.CompactDevelopmentInput(
                    intersections=prior.accepted,
                    max_researched_niches=run.config.max_researched_niches,
                    concepts_per_niche=run.config.concepts_per_niche,
                ).model_dump(mode="python")
            return stage_06.NicheResearchInput(
                intersections=prior.accepted,
                max_researched_niches=run.config.max_researched_niches,
            ).model_dump(mode="python")
        if stage.stage_number == 7:
            if run.config.pipeline_variant.value == "compact_research_first":
                combined = stage_06_compact.CompactDevelopmentOutput.model_validate(previous.output_data)
                return stage_15.ArtworkGenerationInput(
                    prompts=combined.prompts,
                    artwork_variants_per_concept=run.config.artwork_variants_per_concept,
                ).model_dump(mode="python")
            prior = stage_06.NicheResearchOutput.model_validate(previous.output_data)
            return stage_07.ExperienceMiningInput(
                niches=prior.niches,
                evidence=prior.evidence,
            ).model_dump(mode="python")
        if stage.stage_number == 8:
            if run.config.pipeline_variant.value == "compact_research_first":
                prior = stage_15.ArtworkGenerationOutput.model_validate(previous.output_data)
                return stage_16.ArtworkCritiqueInput(artworks=prior.artworks).model_dump(mode="python")
            research = self._stage_repository.get_latest(run.run_id, 6)
            if research is None or not research.output_data:
                raise ValueError("Stage 8 is missing Stage 6 research output.")
            research_output = stage_06.NicheResearchOutput.model_validate(research.output_data)
            mined = stage_07.ExperienceMiningOutput.model_validate(previous.output_data)
            return stage_08.OpportunityScoreInput(
                niches=research_output.niches,
                signals=mined.signals,
            ).model_dump(mode="python")
        if stage.stage_number == 9 and run.config.pipeline_variant.value == "compact_research_first":
            prior = stage_16.ArtworkCritiqueOutput.model_validate(previous.output_data)
            return stage_17.ArtworkRevisionInput(
                artworks=prior.artworks,
                evaluations=prior.evaluations,
            ).model_dump(mode="python")
        if stage.stage_number == 10 and run.config.pipeline_variant.value == "compact_research_first":
            prior = stage_17.ArtworkRevisionOutput.model_validate(previous.output_data)
            return stage_09_gallery.ArtworkGalleryInput(
                artworks=prior.artworks,
                evaluations=prior.evaluations,
                revisions=prior.revisions,
            ).model_dump(mode="python")
        if stage.stage_number == 9:
            prior = stage_08.OpportunityScoringOutput.model_validate(previous.output_data)
            mined = self._stage_repository.get_latest(run.run_id, 7)
            if mined is None or not mined.output_data:
                raise ValueError("Stage 9 is missing Stage 7 experience signals.")
            mined_output = stage_07.ExperienceMiningOutput.model_validate(mined.output_data)
            return stage_09.ConceptGenerationInput(
                niches=prior.niches,
                experience_signals=mined_output.signals,
                concepts_per_niche=run.config.concepts_per_niche,
            ).model_dump(mode="python")
        if stage.stage_number == 10:
            prior = stage_09.ConceptGenerationOutput.model_validate(previous.output_data)
            return stage_10.ConceptCritiqueInput(concepts=prior.concepts).model_dump(mode="python")
        if stage.stage_number == 11:
            prior = stage_10.ConceptCritiqueOutput.model_validate(previous.output_data)
            return stage_11.SimilarityCheckInput(concepts=prior.concepts).model_dump(mode="python")
        if stage.stage_number == 12:
            if previous.stage_number == 11 and previous.output_data:
                prior = stage_11.SimilarityCheckOutput.model_validate(previous.output_data)
                concepts = prior.survivors
            else:
                prior = stage_10.ConceptCritiqueOutput.model_validate(previous.output_data)
                concepts = prior.concepts
                if stage_11_skipped and self._saturation_checker is not None:
                    screened = stage_11.execute(
                        stage_11.SimilarityCheckInput(
                            concepts=concepts,
                            saturation=_saturation_findings(
                                self._saturation_checker,
                                [(concept.concept_id, concept.phrase) for concept in concepts],
                            ),
                        )
                    )
                    concepts = screened.survivors or concepts
            return stage_12.FinalSelectionInput(
                concepts=concepts,
                max_finalists=max(1, run.config.max_researched_niches),
                humor_tone=run.config.humor_tone.value,
            ).model_dump(mode="python")
        if stage.stage_number == 13:
            prior = stage_12.FinalSelectionOutput.model_validate(previous.output_data)
            return stage_13.DesignBriefInput(concepts=prior.finalists).model_dump(mode="python")
        if stage.stage_number == 14:
            prior = stage_13.DesignBriefOutput.model_validate(previous.output_data)
            return stage_14.PromptCompilationInput(briefs=prior.briefs).model_dump(mode="python")
        if stage.stage_number == 15:
            prior = stage_14.PromptCompilationOutput.model_validate(previous.output_data)
            return stage_15.ArtworkGenerationInput(
                prompts=prior.prompts,
                artwork_variants_per_concept=run.config.artwork_variants_per_concept,
            ).model_dump(mode="python")
        if stage.stage_number == 16:
            prior = stage_15.ArtworkGenerationOutput.model_validate(previous.output_data)
            return stage_16.ArtworkCritiqueInput(artworks=prior.artworks).model_dump(mode="python")
        if stage.stage_number == 17:
            prior = stage_16.ArtworkCritiqueOutput.model_validate(previous.output_data)
            if stage.stage_name == "Artwork Results":
                # Runs created before the revision stage used Stage 17 as their terminal gallery.
                # Keep those immutable snapshots readable while new runs use Stage 17 for edits.
                return stage_09_gallery.ArtworkGalleryInput(
                    artworks=prior.artworks,
                    evaluations=prior.evaluations,
                ).model_dump(mode="python")
            return stage_17.ArtworkRevisionInput(
                artworks=prior.artworks,
                evaluations=prior.evaluations,
            ).model_dump(mode="python")
        if stage.stage_number == 18:
            prior = stage_17.ArtworkRevisionOutput.model_validate(previous.output_data)
            return stage_09_gallery.ArtworkGalleryInput(
                artworks=prior.artworks,
                evaluations=prior.evaluations,
                revisions=prior.revisions,
            ).model_dump(mode="python")
        raise StageNotImplementedError(
            f"Stage {stage.stage_number} ({stage.stage_name}) has no registered handler yet."
        )

    def execute(self, run: WorkflowRun, stage: StageExecution, input_data: dict) -> StageResult:
        """Run one supported stage and retain exact input/output payloads for auditability."""

        usage = UsageMetrics()
        if run.config.pipeline_variant == PipelineVariant.SOCIAL_IDENTITY_V2:
            if stage.stage_number == 1:
                input_model = social_identity_v2.SocialIdentityV2Input.model_validate(input_data)
                output, usage = self._finish_social_text(
                    run,
                    input_model,
                    social_identity_v2,
                    social_identity_v2.SocialIdentityV2Output,
                )
                summary = (
                    f"Generated {len(output.candidates)} prompt-focused identity merchandise "
                    f"candidates using {output.model}."
                )
                return StageResult(
                    input_data=input_data,
                    output_data=output.model_dump(mode="python"),
                    output_summary=summary,
                    usage=usage,
                )
            if stage.stage_number == 2:
                identity_input = social_identity_v2_artwork.IdentityV2ArtworkInput.model_validate(
                    input_data
                )
                output = social_identity_v2_artwork.execute(
                    identity_input,
                    run_id=run.run_id,
                    provider=self._image_provider,
                    storage=self._artwork_storage,
                )
                usage = output.usage
                self._artworks.replace_for_run(run.run_id, output.artworks)
                summary = f"Generated {len(output.artworks)} Identity V2 artwork candidates with Grok."
                return StageResult(
                    input_data=identity_input.model_dump(mode="python"),
                    output_data=output.model_dump(mode="python"),
                    output_summary=summary,
                    usage=usage,
                )
            raise StageNotImplementedError(
                f"Identity V2 pipeline does not define Stage {stage.stage_number}."
            )

        if run.config.pipeline_variant == PipelineVariant.SOCIAL_BEHAVIOR_IDENTITY:
            if stage.stage_number == 1:
                input_model = social_behavior_identity.BehaviorIdentityInput.model_validate(input_data)
                output, usage = self._finish_social_text(
                    run,
                    input_model,
                    social_behavior_identity,
                    social_behavior_identity.BehaviorIdentityOutput,
                )
                identity_count = len(
                    {candidate.identity.casefold() for candidate in output.candidates}
                )
                summary = (
                    f"Generated {len(output.candidates)} behavior-led merchandise candidates "
                    f"across {identity_count} evidence-backed audience identities using {output.model}."
                )
                return StageResult(
                    input_data=input_data,
                    output_data=output.model_dump(mode="python"),
                    output_summary=summary,
                    usage=usage,
                )
            if stage.stage_number == 2:
                social_input = social_artwork.SocialArtworkInput.model_validate(input_data)
                output = social_artwork.execute(
                    social_input,
                    run_id=run.run_id,
                    provider=self._image_provider,
                    storage=self._artwork_storage,
                )
                usage = output.usage
                self._artworks.replace_for_run(run.run_id, output.artworks)
                summary = (
                    f"Generated {len(output.artworks)} behavior-first, identity-grounded "
                    "merchandise artworks with Grok."
                )
                return StageResult(
                    input_data=social_input.model_dump(mode="python"),
                    output_data=output.model_dump(mode="python"),
                    output_summary=summary,
                    usage=usage,
                )
            raise StageNotImplementedError(
                f"Behavior-first identity pipeline does not define Stage {stage.stage_number}."
            )

        if run.config.pipeline_variant == PipelineVariant.SOCIAL_IDENTITY_FOCUSED:
            if stage.stage_number == 1:
                input_model = social_identity.SocialIdentityTextInput.model_validate(input_data)
                output, usage = self._finish_social_text(
                    run,
                    input_model,
                    social_identity,
                    social_identity.SocialIdentityTextOutput,
                )
                summary = (
                    f"Generated {len(output.candidates)} identity-focused merchandise text "
                    f"candidates and artwork prompts using {output.model}."
                )
                return StageResult(
                    input_data=input_data,
                    output_data=output.model_dump(mode="python"),
                    output_summary=summary,
                    usage=usage,
                )
            if stage.stage_number == 2:
                identity_input = social_identity_artwork.IdentityArtworkInput.model_validate(input_data)
                output = social_identity_artwork.execute(
                    identity_input,
                    run_id=run.run_id,
                    provider=self._image_provider,
                    storage=self._artwork_storage,
                )
                usage = output.usage
                self._artworks.replace_for_run(run.run_id, output.artworks)
                summary = (
                    f"Generated {len(output.artworks)} identity-focused merchandise artwork "
                    "candidates with Grok."
                )
                return StageResult(
                    input_data=identity_input.model_dump(mode="python"),
                    output_data=output.model_dump(mode="python"),
                    output_summary=summary,
                    usage=usage,
                )
            raise StageNotImplementedError(
                f"Identity-focused social pipeline does not define Stage {stage.stage_number}."
            )

        if run.config.pipeline_variant == PipelineVariant.SOCIAL_BEHAVIOR_TEXT:
            if stage.stage_number == 1:
                input_model = social_behavior.SocialBehaviorTextInput.model_validate(input_data)
                output, usage = self._finish_social_text(
                    run,
                    input_model,
                    social_behavior,
                    social_behavior.SocialBehaviorTextOutput,
                )
                summary = (
                    f"Generated {len(output.candidates)} behavior-based merchandise text candidates "
                    f"and artwork prompts using {output.model}."
                )
                return StageResult(
                    input_data=input_data,
                    output_data=output.model_dump(mode="python"),
                    output_summary=summary,
                    usage=usage,
                )
            if stage.stage_number == 2:
                social_input = social_artwork.SocialArtworkInput.model_validate(input_data)
                output = social_artwork.execute(
                    social_input,
                    run_id=run.run_id,
                    provider=self._image_provider,
                    storage=self._artwork_storage,
                )
                usage = output.usage
                self._artworks.replace_for_run(run.run_id, output.artworks)
                summary = f"Generated {len(output.artworks)} targeted merchandise artwork candidates with Grok."
                return StageResult(
                    input_data=social_input.model_dump(mode="python"),
                    output_data=output.model_dump(mode="python"),
                    output_summary=summary,
                    usage=usage,
                )
            raise StageNotImplementedError(
                f"Social behavior pipeline does not define Stage {stage.stage_number}."
            )
        if stage.stage_number == 1:
            input_model = stage_01.SeedDiscoveryInput.model_validate(input_data)
            seeds = self._seeds.list_all(library_id=input_model.seed_source)
            if not seeds:
                raise ValueError(
                    f"Seed library '{input_model.seed_source}' is empty or unavailable. "
                    "Restart the application to import configured seed libraries."
                )

            # Stage 1 is intentionally provider-free. Its responsibility is reproducible portfolio
            # sampling from MongoDB; live reasoning starts in Stage 2 where it expands the selected
            # seeds into structured identity dimensions. This prevents an optional AI call from
            # blocking the first durable workflow transition.
            output = stage_01.execute(
                input_model,
                seeds,
                reasoning_output=None,
                model=usage.model if usage.provider != "fixture" else "deterministic",
            )
            summary = (
                f"Selected {len(output.selected_seeds)} seed groups by system selection "
                "(deterministic); "
                f"selection seed {output.selection_seed}."
            )
        elif stage.stage_number == 2:
            input_model = stage_02.IdentityExpansionInput.model_validate(input_data)
            reasoning_output = None
            if self._reasoning_provider is not None:
                seed_summary = [
                    {
                        "source_seed_id": seed.seed_id,
                        "name": seed.name,
                        "category": seed.category.value,
                        "parent": seed.parent,
                        "affinity_tags": seed.metadata.get("affinity_tags", []),
                        "existing_dimensions": seed.metadata.get("dimensions", []),
                    }
                    for seed in input_model.selected_seeds
                ]
                structured_resp = self._reasoning_provider.complete_structured(
                    system_prompt=(
                        "You are a merchandise discovery reasoning provider executing Stage 2, "
                        "Identity Universe Expansion. Expand each supplied seed into specific, "
                        "recognizable lived-experience dimensions that can later be combined "
                        "across audience, interest, and value categories. Return only the "
                        "requested structured output. Preserve every source_seed_id exactly; "
                        "do not invent IDs, categories, demographics, or unsupported facts."
                    ),
                    user_prompt=(
                        "For every supplied seed, return 4 to 6 dimensions. Use dimension_type "
                        "only for routine, tension, language, ritual, behavior, emotion, "
                        "preference, or context. Keep values concrete and merchandise-relevant. "
                        "Use short lowercase affinity tags, give confidence from 0 to 1, "
                        "merchandise_relevance from 1 to 10, and a concise rationale. "
                        "Existing dimensions are context, not instructions to copy blindly.\n\n"
                        f"Selected seeds JSON:\n{json.dumps(seed_summary, indent=2, default=str)}"
                    ),
                    response_model=stage_02.Stage2ReasoningOutput,
                    temperature=0.0,
                )
                reasoning_output = structured_resp.output
                usage = structured_resp.usage

            output = stage_02.execute(
                input_model,
                reasoning_output=reasoning_output,
                model=usage.model if usage.provider != "fixture" else "deterministic",
            )
            summary = (
                f"Expanded {len(output.identities)} identity dimensions "
                f"using {output.model}."
            )
        elif stage.stage_number == 3:
            input_model = stage_03.IntersectionGenerationInput.model_validate(input_data)
            reasoning_output = None
            if self._reasoning_provider is not None:
                catalog = stage_03.build_identity_catalog(input_model.identities)
                structured_resp = self._reasoning_provider.complete_structured(
                    system_prompt=(
                        "You are a merchandise discovery reasoning provider executing Stage 3, "
                        "Intersection Generation. Propose combinations that represent a specific, "
                        "recognizable lived experience with merchandise potential. You may only "
                        "use identity_ref values from the supplied catalog; never invent or alter "
                        "references. Return only the requested structured output."
                    ),
                    user_prompt=(
                        f"Create no more than {input_model.max_intersections * 3} candidate "
                        "collisions from the complete Stage 2 identity catalog below. Each "
                        "intersection must contain 2 to 4 identity references from two different "
                        "lives: a job and a hobby, an identity and a life situation, or two "
                        "communities. Do not prefer natural pairs, and do not treat shared affinity "
                        "tags as a bonus. Score the collision for unexpectedness, whether a real "
                        "person is both, and whether a stranger still gets it. A proposal may use "
                        "at most two dimensions from the same source seed and must use at least two "
                        "source seeds. Explain the collision in composition_rationale and score "
                        "distinctiveness from 1 to 10. Reject a second proposal that is the same "
                        "joke. Do not evaluate the final portfolio yet; that is Stage 4.\n\n"
                        f"Identity catalog ({len(catalog)} records):\n"
                        f"{json.dumps(catalog, indent=2, default=str)}"
                    ),
                    response_model=stage_03.Stage3ReasoningOutput,
                    temperature=0.0,
                )
                reasoning_output = structured_resp.output
                usage = structured_resp.usage

            output = stage_03.execute(
                input_model,
                run_id=run.run_id,
                reasoning_output=reasoning_output,
                model=usage.model if usage.provider != "fixture" else "deterministic",
            )
            if reasoning_output is not None:
                summary = (
                    f"AI proposed {output.provider_proposals_count} intersections; retained "
                    f"{len(output.intersections)} after system validation."
                )
            else:
                summary = f"Generated {len(output.intersections)} candidate intersections deterministically."
        elif stage.stage_number == 4:
            input_model = stage_04.CoherenceInput.model_validate(input_data)
            provider_output = None
            if self._reasoning_provider is not None:
                try:
                    intersection_catalog = [
                        {
                            "intersection_id": intersection.intersection_id,
                            "identities": intersection.identities,
                            "source_seed_ids": intersection.source_seed_ids,
                            "shared_tags": intersection.metadata.get("shared_tags", []),
                            "collision_score": intersection.metadata.get("collision_score"),
                            "pair_kind": intersection.metadata.get("pair_kind", ""),
                            "composition_rationale": intersection.metadata.get(
                                "composition_rationale", ""
                            ),
                        }
                        for intersection in input_model.intersections
                    ]
                    structured_response = self._reasoning_provider.complete_structured(
                        system_prompt=stage_04.reasoning_instructions(),
                        user_prompt=(
                            f"Select exactly {min(input_model.max_researched_niches, len(input_model.intersections))} "
                            "intersection(s) for niche research. Choose collisions a real person could "
                            "be, that a stranger still gets, and that are not already a saturated "
                            "natural pair. Mix warm, dry, and dark angles and reject duplicate jokes. "
                            "For every selected candidate provide a selection_reason "
                            "that refers to the supplied identities, experience signals, or rationale "
                            "and explains its distinct portfolio angle; "
                            "do not use generic reasons such as 'high potential'. Also provide a "
                            "coherence and research-value scores from 0 to 10, and confidence from 0 to 1. "
                            "Do not "
                            "return evaluations for candidates you did not select.\n\n"
                            f"Intersections JSON:\n{json.dumps(intersection_catalog, indent=2, default=str)}"
                        ),
                        response_model=stage_04.Stage4ReasoningOutput,
                        temperature=0.0,
                    )
                    provider_output = structured_response.output
                    usage = structured_response.usage
                except Exception as error:  # Log context, then fail the live stage.
                    logger.warning(
                        "Stage 4 provider selection failed; live stage will fail: %s",
                        error,
                    )
                    raise
            try:
                output = stage_04.execute(
                    input_model,
                    reasoning_output=provider_output,
                    model=usage.model if usage.provider != "fixture" else "deterministic",
                )
                self._intersections.replace_for_run(run.run_id, output.intersections)
                selection_actor = "AI" if output.model != "deterministic" else "Deterministic fixture logic"
                summary = (
                    f"{selection_actor} selected {len(output.selected_intersection_ids)} of "
                    f"{len(output.intersections)} intersections for niche research."
                )
            except ValueError as error:
                # Invalid provider selection is a stage failure, not a reason to hide the live
                # provider problem behind deterministic output.
                logger.warning(
                    "Stage 4 provider output failed semantic validation; live stage will fail: %s",
                    error,
                )
                raise
        elif stage.stage_number == 5:
            input_model = stage_05.PreResearchFilterInput.model_validate(input_data)
            output = stage_05.execute(input_model)
            self._intersections.replace_for_run(run.run_id, output.all_intersections)
            summary = (
                f"Passed through {len(output.accepted)} AI-selected intersections; "
                f"retained {len(output.rejected)} non-selected candidates for audit."
            )
        elif stage.stage_number == 6:
            if run.config.pipeline_variant.value == "compact_research_first":
                input_model = stage_06_compact.CompactDevelopmentInput.model_validate(input_data)
                output = stage_06_compact.execute(
                    input_model,
                    research_provider=self._research_provider,
                    reasoning_provider=self._reasoning_provider,
                    run_id=run.run_id,
                )
                usage = output.usage
                self._niches.replace_for_run(run.run_id, output.niches)
                self._evidence.replace_for_run(run.run_id, output.evidence)
                self._concepts.replace_for_run(run.run_id, output.concepts)
                summary = (
                    f"Researched {len(output.niches)} niches and generated "
                    f"{len(output.concepts)} evidence-backed concepts using {output.model}."
                )
                return StageResult(
                    input_data=input_data,
                    output_data=output.model_dump(mode="python"),
                    output_summary=summary,
                    usage=usage,
                )
            input_model = stage_06.NicheResearchInput.model_validate(input_data)
            output = stage_06.execute(input_model, self._research_provider, run_id=run.run_id)
            usage = output.usage
            self._niches.replace_for_run(run.run_id, output.niches)
            self._evidence.replace_for_run(run.run_id, output.evidence)
            summary = (
                f"Researched {len(output.niches)} niches and stored "
                f"{len(output.evidence)} source records."
            )
        elif stage.stage_number == 7 and run.config.pipeline_variant.value == "compact_research_first":
            input_model = stage_15.ArtworkGenerationInput.model_validate(input_data)
            output = stage_15.execute(
                input_model,
                self._image_provider,
                self._artwork_storage,
            )
            usage = output.usage
            self._artworks.replace_for_run(run.run_id, output.artworks)
            summary = f"Generated {len(output.artworks)} compact-pipeline artwork candidates."
        elif stage.stage_number == 8 and run.config.pipeline_variant.value == "compact_research_first":
            input_model = stage_16.ArtworkCritiqueInput.model_validate(input_data)
            output, usage = self._critique_artworks(input_model)
            self._artworks.replace_for_run(run.run_id, output.artworks)
            accepted = sum(item.decision.value == "accept" for item in output.evaluations)
            summary = f"Luna reviewed {len(output.evaluations)} artworks; {accepted} need no edit."
        elif stage.stage_number == 9 and run.config.pipeline_variant.value == "compact_research_first":
            input_model = stage_17.ArtworkRevisionInput.model_validate(input_data)
            output = stage_17.execute(
                input_model,
                self._image_provider,
                self._artwork_storage,
            )
            usage = output.usage
            self._artworks.replace_for_run(run.run_id, output.artworks)
            revised = sum(item.revised for item in output.revisions)
            summary = f"Grok revised {revised} artwork candidates; {len(output.artworks) - revised} unchanged."
        elif stage.stage_number == 10 and run.config.pipeline_variant.value == "compact_research_first":
            input_model = stage_09_gallery.ArtworkGalleryInput.model_validate(input_data)
            output = stage_09_gallery.execute(input_model)
            summary = output.summary
        elif stage.stage_number == 7:
            input_model = stage_07.ExperienceMiningInput.model_validate(input_data)
            provider_output = None
            if self._reasoning_provider is not None and input_model.niches:
                evidence_catalog = [
                    {
                        "niche_id": evidence.niche_id,
                        "evidence_id": evidence.evidence_id,
                        "title": evidence.title,
                        "source": evidence.source,
                        "excerpt": evidence.excerpt,
                        "url": evidence.url,
                    }
                    for evidence in input_model.evidence
                ]
                niche_catalog = [
                    {
                        "niche_id": niche.niche_id,
                        "name": niche.name,
                        "intersection_id": niche.intersection_id,
                        "coherence_score": niche.coherence_score,
                    }
                    for niche in input_model.niches
                ]
                try:
                    structured_response = self._reasoning_provider.complete_structured(
                        system_prompt=(
                            "You are a merchandise discovery research analyst executing Stage 7, "
                            "Experience Mining. Extract recurring lived-experience signals from the "
                            "supplied evidence. Return exactly one signal record for every supplied "
                            "niche_id, preserve all IDs exactly, and cite only evidence IDs belonging "
                            "to that niche. Do not invent observations, citations, or unsupported "
                            "market claims. Return only the requested structured output."
                        ),
                        user_prompt=(
                            "For each niche, identify repeated community language, frustrations, "
                            "rituals, and emotional signals that are actually supported by its evidence. "
                            "Use concise statements, include the exact evidence IDs supporting the "
                            "statements, and set confidence from 0 to 1 based on consistency and source "
                            "support. If evidence is weak, return empty signal lists and explain that "
                            "limitation in experience_summary. Do not infer demographics or demand that "
                            "are not present in the evidence.\n\n"
                            f"Niches JSON:\n{json.dumps(niche_catalog, indent=2, default=str)}\n\n"
                            f"Evidence JSON:\n{json.dumps(evidence_catalog, indent=2, default=str)}"
                        ),
                        response_model=stage_07.Stage7ReasoningOutput,
                        temperature=0.0,
                    )
                    provider_output = structured_response.output
                    usage = structured_response.usage
                except Exception as error:  # Log context, then fail the live stage.
                    logger.warning(
                        "Stage 7 provider mining failed; live stage will fail: %s",
                        error,
                    )
                    raise
            try:
                output = stage_07.execute(
                    input_model,
                    reasoning_output=provider_output,
                    model=usage.model if usage.provider != "fixture" else "deterministic",
                )
                summary = (
                    f"Mined recurring experience signals for {len(output.signals)} niches "
                    f"using {output.model}."
                )
            except ValueError as error:
                # Invalid evidence lineage is a stage failure, not a reason to hide the live
                # provider problem behind deterministic output.
                logger.warning(
                    "Stage 7 provider output failed semantic validation; live stage will fail: %s",
                    error,
                )
                raise
        elif stage.stage_number == 8:
            input_model = stage_08.OpportunityScoreInput.model_validate(input_data)
            provider_output = None
            if self._reasoning_provider is not None and input_model.niches:
                signal_by_niche = {signal.niche_id: signal for signal in input_model.signals}
                scoring_catalog = [
                    {
                        "niche_id": niche.niche_id,
                        "name": niche.name,
                        "coherence_score": niche.coherence_score,
                        "evidence_count": niche.evidence_count,
                        "validated": niche.validated,
                        "experience_signals": (
                            signal_by_niche[niche.niche_id].model_dump(mode="python")
                            if niche.niche_id in signal_by_niche
                            else None
                        ),
                    }
                    for niche in input_model.niches
                ]
                try:
                    structured_response = self._reasoning_provider.complete_structured(
                        system_prompt=(
                            "You are a merchandise discovery strategist executing Stage 8, "
                            "Opportunity Scoring. Evaluate only the supplied researched niches and "
                            "signals. Return exactly one evaluation for every supplied niche_id, "
                            "preserve IDs exactly, and do not claim market size, revenue, demand, or "
                            "competitive facts that are not present in the input. Return only the "
                            "requested structured output."
                        ),
                        user_prompt=(
                            "For each niche, assign bounded qualitative scores using these exact "
                            "ranges: experience_clarity 0-30, audience_fit 0-20, and "
                            "differentiation 0-20. Use the supplied research evidence count and mined "
                            "signals as context, but do not score evidence_strength: the application "
                            "calculates that deterministically. Give a concise rationale grounded in "
                            "the supplied records.\n\n"
                            f"Scoring input JSON:\n{json.dumps(scoring_catalog, indent=2, default=str)}"
                        ),
                        response_model=stage_08.Stage8ReasoningOutput,
                        temperature=0.0,
                    )
                    provider_output = structured_response.output
                    usage = structured_response.usage
                except Exception as error:  # Log context, then fail the live stage.
                    logger.warning(
                        "Stage 8 provider scoring failed; live stage will fail: %s",
                        error,
                    )
                    raise
            try:
                output = stage_08.execute(
                    input_model,
                    reasoning_output=provider_output,
                    model=usage.model if usage.provider != "fixture" else "deterministic",
                )
                summary = (
                    f"Scored and ranked {len(output.scores)} researched niches "
                    f"using {output.model}."
                )
            except ValueError as error:
                # Exact niche coverage is mandatory; malformed AI scoring must remain visible.
                logger.warning(
                    "Stage 8 provider output failed semantic validation; live stage will fail: %s",
                    error,
                )
                raise
            self._niches.replace_for_run(run.run_id, output.niches)
        elif stage.stage_number == 9:
            input_model = stage_09.ConceptGenerationInput.model_validate(input_data)
            has_valid_niches = any(
                niche.validated and bool(niche.experience_summary) for niche in input_model.niches
            )
            provider_output, usage = (
                self._reason(
                    "Stage 9 merchandise concept generation",
                    input_data,
                    stage_09.Stage9ReasoningOutput,
                    instructions=stage_09.reasoning_instructions(run.config.humor_tone),
                )
                if has_valid_niches
                else (None, UsageMetrics())
            )
            # Live provider errors intentionally propagate from _reason. A failed AI stage must be
            # visible to the operator rather than appearing successful with deterministic output.
            output = stage_09.execute(
                input_model,
                reasoning_output=provider_output,
                model=usage.model if usage.provider != "fixture" else "deterministic",
            )
            self._concepts.replace_for_run(run.run_id, output.concepts)
            summary = (
                f"Generated {len(output.concepts)} specific merchandise concepts using {output.model}; "
                f"rejected {len(output.rejected_proposals)} generic proposals."
            )
        elif stage.stage_number == 10:
            input_model = stage_10.ConceptCritiqueInput.model_validate(input_data)
            provider_output, usage = (
                self._reason(
                    "Stage 10 concept critique",
                    input_data,
                    stage_10.Stage10ReasoningOutput,
                    instructions=(
                        "Score personal recognition, niche specificity, and visual distinctiveness "
                        "in addition to authenticity, clarity, wearability, and commercial potential. "
                        "Reject concepts that sound like broad categories or that lack a recognizable "
                        "moment, insider cue, emotional tension, or concrete visual hook."
                    ),
                )
                if input_model.concepts
                else (None, UsageMetrics())
            )
            # Stage 10 validates provider IDs and recomputes score/verdict locally; provider errors
            # are not swallowed so live-mode output remains honest.
            output = stage_10.execute(
                input_model,
                reasoning_output=provider_output,
                model=usage.model if usage.provider != "fixture" else "deterministic",
            )
            self._concepts.replace_for_run(run.run_id, output.concepts)
            summary = f"Critiqued {len(output.evaluations)} merchandise concepts using {output.model}."
        elif stage.stage_number == 11:
            input_model = stage_11.SimilarityCheckInput.model_validate(input_data)
            if self._saturation_checker is not None and not input_model.saturation:
                input_model = input_model.model_copy(
                    update={
                        "saturation": _saturation_findings(
                            self._saturation_checker,
                            [(concept.concept_id, concept.phrase) for concept in input_model.concepts],
                        )
                    }
                )
            output = stage_11.execute(input_model)
            self._concepts.replace_for_run(run.run_id, output.concepts)
            summary = (
                f"Screened {len(output.checks)} concepts; "
                f"{len(output.survivors)} survived the optional duplicate check."
            )
        elif stage.stage_number == 12:
            input_model = stage_12.FinalSelectionInput.model_validate(input_data)
            provider_output, usage = (
                self._reason(
                    "Stage 12 final concept selection",
                    input_data,
                    stage_12.Stage12ReasoningOutput,
                    instructions=(
                        "Compare every concept on distinctiveness, emotional recognition, natural "
                        "wording, giftability, commercial appeal, and visual potential. Return one "
                        "evaluation for every concept ID exactly once, with each score from 0 to 10 "
                        "and a concise rationale. Do not select or reject concepts; the application "
                        "will combine the dimensions and select only concepts already marked KEEP. "
                        "When the run tone is dark, giftability must not veto or down-rank a line."
                    ),
                )
                if input_model.concepts
                else (None, UsageMetrics())
            )
            output = stage_12.execute(
                input_model,
                reasoning_output=provider_output,
                model=usage.model if usage.provider != "fixture" else "deterministic",
            )
            self._concepts.replace_for_run(run.run_id, output.concepts)
            summary = f"Selected {len(output.finalists)} concept finalists using {output.model}."
        elif stage.stage_number == 13:
            input_model = stage_13.DesignBriefInput.model_validate(input_data)
            provider_output, usage = (
                self._reason(
                    "Stage 13 structured design brief generation",
                    input_data,
                    stage_13.Stage13ReasoningOutput,
                    instructions=(
                        "Return one complete design brief for every supplied finalist concept. "
                        "Preserve each concept ID and exact phrase exactly. Include target audience, "
                        "2 to 4 concrete audience_visual_cues that visibly identify the audience "
                        "without logos or identifiable institutions, core concept, emotional idea, "
                        "illustration style, main subject, supporting "
                        "visual elements, composition, typography direction, palette direction, "
                        "detail level, intended merchandise type, visual constraints, and things to "
                        "avoid. Design every brief as a die-cut vinyl sticker: flat vector "
                        "illustration, bold clean outlines, flat colors, one centered isolated "
                        "subject, and a plain white background. Keep the exact phrase to roughly "
                        "about 4 to 14 words and joke-shaped, or make the sticker image-only when words "
                        "are unnecessary. "
                        "Set intended merchandise type to die-cut vinyl sticker. Add scene or "
                        "landscape backgrounds, full-bleed backgrounds, realistic shading, and "
                        "poster layouts to things to avoid."
                    ),
                )
                if input_model.concepts
                else (None, UsageMetrics())
            )
            output = stage_13.execute(
                input_model,
                reasoning_output=provider_output,
                model=usage.model if usage.provider != "fixture" else "deterministic",
            )
            self._briefs.replace_for_run(run.run_id, output.briefs)
            summary = f"Created {len(output.briefs)} structured design briefs using {output.model}."
        elif stage.stage_number == 14:
            input_model = stage_14.PromptCompilationInput.model_validate(input_data)
            output = stage_14.execute(input_model)
            summary = f"Compiled {len(output.prompts)} constrained artwork prompts."
        elif stage.stage_number == 15:
            input_model = stage_15.ArtworkGenerationInput.model_validate(input_data)
            output = stage_15.execute(
                input_model,
                self._image_provider,
                self._artwork_storage,
            )
            usage = output.usage
            self._artworks.replace_for_run(run.run_id, output.artworks)
            summary = f"Generated {len(output.artworks)} artwork candidates."
        elif stage.stage_number == 16:
            input_model = stage_16.ArtworkCritiqueInput.model_validate(input_data)
            output, usage = self._critique_artworks(input_model)
            self._artworks.replace_for_run(run.run_id, output.artworks)
            accepted = sum(item.decision.value == "accept" for item in output.evaluations)
            summary = f"Luna reviewed {len(output.evaluations)} artworks; {accepted} need no edit."
        elif stage.stage_number == 17:
            if stage.stage_name == "Artwork Results":
                # Historical Stage 17 was already a terminal gallery; do not reinterpret its
                # persisted input as a revision request when an old run is opened or resumed.
                input_model = stage_09_gallery.ArtworkGalleryInput.model_validate(input_data)
                output = stage_09_gallery.execute(input_model)
                summary = output.summary
            else:
                input_model = stage_17.ArtworkRevisionInput.model_validate(input_data)
                output = stage_17.execute(
                    input_model,
                    self._image_provider,
                    self._artwork_storage,
                )
                usage = output.usage
                self._artworks.replace_for_run(run.run_id, output.artworks)
                revised = sum(item.revised for item in output.revisions)
                summary = f"Grok revised {revised} artwork candidates; {len(output.artworks) - revised} unchanged."
        elif stage.stage_number == 18:
            # Final results are display-only. No human approval gate or second Luna verification is
            # introduced after Grok's targeted edit.
            input_model = stage_09_gallery.ArtworkGalleryInput.model_validate(input_data)
            output = stage_09_gallery.execute(input_model)
            summary = output.summary
        else:
            raise StageNotImplementedError(
                f"Stage {stage.stage_number} ({stage.stage_name}) has no registered handler yet."
            )

        return StageResult(
            input_data=input_model.model_dump(mode="python"),
            output_data=output.model_dump(mode="python"),
            output_summary=summary,
            usage=usage,
        )
