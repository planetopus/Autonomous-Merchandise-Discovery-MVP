"""Executor for discovery stages and optional provider-backed reasoning.

The executor owns orchestration concerns: loading prior stage outputs, supplying repositories and
providers to stage functions, and persisting artifact snapshots. Each stage module remains
independently portable and provider dependencies are injected here.
"""

import json
import logging
import random
from concurrent.futures import ThreadPoolExecutor

from merchandise_discovery.application.stage_executor import StageNotImplementedError, StageResult
from merchandise_discovery.domain.humor import (
    HumorCritiqueBatch,
    LineReview,
    LineReviewRecord,
    NichePairBatch,
    NichePairRecord,
    PlaybookPatternRecord,
    apply_jargon_cap,
    apply_line_caps,
    apply_line_critic,
    apply_pun_cap,
    apply_trope_cap,
    critic_average,
    keep_strong_pairs,
    line_is_pun,
    member_would_not_buy,
    niche_pair_request,
    primary_wit_share,
    pun_examples_block,
    pun_share_is_thin,
    reading_failed,
    synergy_failed,
    tired_trope_block,
)
from merchandise_discovery.domain.humor_playbook import build_playbook, playbook_prompt
from merchandise_discovery.domain.humor_references import (
    HumorReference,
    HumorReferenceLoadError,
    copied_from_source,
    extract_market_signal,
    identity_pick_bucket,
    is_too_similar_to_references,
    market_signal_prompt,
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
from merchandise_discovery.infrastructure.ant_ratings_loader import (
    ant_calibration_block,
    load_ant_ratings,
    sample_ant_ratings,
    style_examples_block,
)
from merchandise_discovery.infrastructure.humor_lab_loader import (
    gold_lines_block,
    load_humor_lab,
    merge_lab_playbook,
)
from merchandise_discovery.infrastructure.identity_atlas_loader import (
    atlas_prompt,
    infer_who_its_for,
    load_identity_atlas,
    sample_overlap_pairs,
    self_ownable_block,
    split_identity_names,
    subgroup_context,
)
from merchandise_discovery.infrastructure.line_categorizer import attach_categories
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


def _social_output_data(output) -> dict:
    """Persist the stage, the shop categories, and which identity bucket the run used."""

    data = attach_categories(output.model_dump(mode="python"))
    bucket = str(data.get("identity_bucket") or "")
    for candidate in data.get("candidates") or []:
        if isinstance(candidate, dict):
            candidate["identity_bucket"] = bucket
    return data


def _pair_in_bank(niche_a: str, niche_b: str, bank: list[dict]) -> bool:
    """True when the model stayed on a pair the atlas sample already offered."""

    left = niche_a.strip().casefold()
    right = niche_b.strip().casefold()
    for item in bank:
        sides = {
            str(item.get("niche_a", "")).strip().casefold(),
            str(item.get("niche_b", "")).strip().casefold(),
        }
        if sides == {left, right}:
            return True
    return False


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
        ebay_checker=None,
        listing_search=None,
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
        self._ebay_checker = ebay_checker
        self._listing_search = listing_search

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

        usage = UsageMetrics()
        try:
            reasoning_output, usage, selection, line_reviews, playbook, pair_meta = self._social_reasoning(
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
            output = self._stamp_humor_context(
                output,
                selection,
                playbook,
                getattr(self, "_market_signal", None),
            )
            pair_update = {"line_reviews": line_reviews}
            supplied_a = str(getattr(input_model, "niche_a", "") or "").strip()
            supplied_b = str(getattr(input_model, "niche_b", "") or "").strip()
            if pair_meta:
                pair_update.update(pair_meta)
            elif supplied_a and supplied_b:
                pair_update["niche_pair_a"] = supplied_a
                pair_update["niche_pair_b"] = supplied_b
            pair_update["atlas_subgroups_loaded"] = len(load_identity_atlas().subgroups)
            return output.model_copy(update=pair_update), usage
        except Exception as error:
            if getattr(error, "stage_usage", None) is None:
                error.stage_usage = usage if usage.request_count or usage.total_tokens else getattr(
                    self, "_social_usage", None
                )
            if getattr(error, "stage_output", None) is None:
                error.stage_output = getattr(self, "_social_preview", None)
            raise

    def _social_reasoning(self, run: WorkflowRun, input_model, pipeline_module, output_model):
        """Collect comments, draft joke-shaped lines, then let a critic cut them."""

        selection, references = self._humor_selection(run, input_model)
        market = extract_market_signal(references)
        self._market_signal = market
        lab = load_humor_lab()
        playbook = merge_lab_playbook(build_playbook([]), lab.playbook)
        humor_block = playbook_prompt(playbook, limit=8) + gold_lines_block(lab.gold_lines[:6])
        style_block = style_examples_block(
            load_ant_ratings(),
            rng=random.Random(getattr(run, "run_id", "style")),
        )
        writer_block = (
            style_block + pun_examples_block() + market_signal_prompt(market) + humor_block
        )
        if self._reasoning_provider is None:
            return None, UsageMetrics(), selection, [], playbook, None
        supplied_a = str(getattr(input_model, "niche_a", "") or "").strip()
        supplied_b = str(getattr(input_model, "niche_b", "") or "").strip()
        supplied_names = split_identity_names(supplied_a, supplied_b)
        atlas = load_identity_atlas()
        share = min(1.0, max(0.0, float(getattr(run.config, "social_trending_share", 0.6))))
        if len(supplied_names) >= 2:
            bucket = "supplied"
        else:
            bucket = identity_pick_bucket(
                share,
                random.Random(run.run_id),
                has_buyers=bool(market.identities),
            )
        self._identity_bucket = bucket
        self._trending_share = share
        pair_bank = self._atlas_pair_bank(
            atlas,
            supplied_names[0] if len(supplied_names) == 1 else "",
            self._recent_catalog_terms(run),
            market.token_weights if bucket == "trending" else None,
        )
        need_pair = len(supplied_names) < 2
        pair_meta = None
        usage = UsageMetrics()
        self._social_usage = usage
        self._social_preview = None
        warnings: list[str] = []
        if len(supplied_names) >= 2:
            pair_meta = {
                "niche_pair_a": supplied_names[0],
                "niche_pair_b": " + ".join(supplied_names[1:]),
                "pairing_score": None,
                "pairing_reason": "The user named these identities.",
                "niche_pair_candidates": [],
            }
            input_model = input_model.model_copy(
                update={
                    "niche_a": pair_meta["niche_pair_a"],
                    "niche_b": pair_meta["niche_pair_b"],
                }
            )
        # The pair call does not need Reddit, so the two waits overlap.
        with ThreadPoolExecutor(max_workers=2) as pool:
            quote_job = pool.submit(self._collect_reddit_quotes, input_model)
            pair_job = (
                pool.submit(self._score_niche_pairs, input_model, pair_bank, supplied_names[:1])
                if need_pair
                else None
            )
            quotes = quote_job.result()
            if pair_job is not None:
                pair_meta, pair_usage, pair_warning = pair_job.result()
                usage = self._add_usage(usage, pair_usage)
                self._note_social_progress(usage, pair_meta, [], [], warnings)
                if pair_warning:
                    warnings.append(pair_warning)
                input_model = input_model.model_copy(
                    update={
                        "niche_a": pair_meta["niche_pair_a"],
                        "niche_b": pair_meta["niche_pair_b"],
                    }
                )
        domains = None
        if not quotes:
            domains = tuple(
                "reddit.com" if source.value == "reddit" else "x.com" for source in input_model.sources
            )
        chosen_names = split_identity_names(
            str(getattr(input_model, "niche_a", "") or ""),
            str(getattr(input_model, "niche_b", "") or ""),
        )
        groups, slang = subgroup_context(atlas, *chosen_names)
        atlas_block = atlas_prompt(groups, slang)
        ownable = self_ownable_block(groups)
        critic_rubric = "\n".join(
            part for part in ((lab.rubric or "")[:1200], ownable) if part
        )
        user_prompt = pipeline_module.build_user_prompt(
            input_model,
            draft_count=12,
            quotes=quotes,
            humor_reference_block=writer_block + atlas_block,
        )
        response = self._reasoning_provider.complete_structured(
            system_prompt=pipeline_module.reasoning_instructions(run.config.humor_tone),
            user_prompt=user_prompt,
            response_model=output_model,
            web_search_domains=domains,
            reasoning_effort="low",
        )
        usage = self._add_usage(usage, response.usage)
        drafted = list(getattr(response.output, "candidates", []))
        candidates, reviews = self._drop_unoriginal(drafted, references, lab.gold_lines)
        if candidates:
            candidates, critic_usage, critic_rows = self._critic_pass(
                run,
                candidates,
                len(candidates),
                humor_block,
                critic_rubric,
            )
            usage = self._add_usage(usage, critic_usage)
            reviews.extend(critic_rows)
        if self._spread_is_thin(drafted) or self._wit_is_thin(drafted) or pun_share_is_thin(drafted):
            spread, spread_usage, spread_reviews = self._rewrite_for_spread(
                run,
                input_model,
                output_model,
                pipeline_module,
                writer_block + atlas_block,
                references,
                lab.gold_lines,
                critic_rubric,
                humor_block,
            )
            usage = self._add_usage(usage, spread_usage)
            reviews.extend(spread_reviews)
            wider = bool(spread) and not self._spread_is_thin(spread)
            puns_caught_up = (
                bool(spread)
                and pun_share_is_thin(drafted)
                and not pun_share_is_thin(spread)
                and not self._wit_is_thin(spread)
            )
            if wider or puns_caught_up:
                candidates = spread
            else:
                if spread:
                    candidates = self._best_available(spread, candidates, input_model.candidate_count)
                warnings.append(
                    "The first batch sat on too few patterns or truths. "
                    "Showing the widest lines available."
                )
        self._note_social_progress(usage, pair_meta, candidates or drafted, reviews, warnings)
        if self._needs_absurd_stacks(candidates, input_model.candidate_count):
            filled, fill_usage, fill_reviews = self._fill_absurd_stacks(
                run,
                input_model,
                output_model,
                pipeline_module,
                writer_block + atlas_block,
                references,
                lab.gold_lines,
                critic_rubric,
                humor_block,
            )
            usage = self._add_usage(usage, fill_usage)
            reviews.extend(fill_reviews)
            candidates = self._merge_stacks(candidates, filled)
            if self._needs_absurd_stacks(candidates, input_model.candidate_count):
                warnings.append(
                    "Fewer than two absurd identity stack lines survived. "
                    "Showing the best lines anyway."
                )
        chosen = response.output
        usable = self._without_copied_lines(drafted, reviews)
        if len(candidates) < input_model.candidate_count:
            warnings.append(
                "Fewer lines cleared the critic than requested. Showing the best lines anyway."
            )
            candidates = self._best_available(usable, candidates, input_model.candidate_count)
        if not candidates and usable:
            warnings.append("No line cleared the critic. Showing the drafted lines anyway.")
            candidates = usable[: input_model.candidate_count]
        ordered = self._order_with_stacks(candidates, input_model.candidate_count) or candidates[:1]
        ordered, reviews = self._apply_who_its_for(ordered, reviews, atlas, chosen_names)
        ordered, reviews, sale_note = self._drop_already_for_sale(ordered, reviews)
        if sale_note:
            warnings.append(sale_note)
        search_usage = getattr(self._listing_search, "usage", None)
        if search_usage is not None and getattr(search_usage, "request_count", 0):
            usage = self._add_usage(usage, search_usage)
        output = chosen.model_copy(
            update={
                "candidates": ordered,
                "stage_warning": " ".join(warnings),
            }
        )
        output = self._drop_crowded_lines(output)
        self._note_social_progress(usage, pair_meta, output.candidates, reviews, warnings)
        return output, usage, selection, reviews, playbook, pair_meta

    def _apply_who_its_for(self, candidates, reviews, atlas, names: list[str]):
        """Fill 2 to 4 buyer categories on every surviving line and critic row."""

        groups, _slang = subgroup_context(atlas, *names)
        updated = []
        by_text: dict[str, list[str]] = {}
        for candidate in candidates:
            text = str(getattr(candidate, "artwork_text", "") or "")
            labels = infer_who_its_for(
                list(getattr(candidate, "who_its_for", []) or []),
                names,
                groups,
                atlas,
            )
            by_text[text] = labels
            if hasattr(candidate, "model_copy"):
                updated.append(candidate.model_copy(update={"who_its_for": labels}))
            else:
                updated.append(candidate)
        stamped = []
        for review in reviews:
            labels = by_text.get(review.artwork_text) or infer_who_its_for([], names, groups, atlas)
            stamped.append(review.model_copy(update={"who_its_for": labels}))
        return updated, stamped

    def _drop_already_for_sale(self, candidates, reviews):
        """Flag final lines already sold. Web search always runs; eBay is an extra."""

        clean = []
        flagged = False
        for candidate in candidates:
            text = str(getattr(candidate, "artwork_text", "") or "")
            hit, url = self._listing_hit(text)
            if not hit:
                clean.append(candidate)
                continue
            flagged = True
            reason = "already for sale" if not url else f"already for sale: {url}"
            reviews.append(
                LineReviewRecord(
                    artwork_text=text,
                    pattern=str(getattr(candidate, "pattern", "") or ""),
                    who_its_for=list(getattr(candidate, "who_its_for", []) or []),
                    kept=False,
                    reason=reason,
                )
            )
        if clean and flagged:
            return clean, reviews, "Some lines were already for sale and were dropped."
        if flagged:
            return (
                candidates,
                reviews,
                "Every final line is already for sale. Keeping them so the run is not empty.",
            )
        return candidates, reviews, ""

    def _listing_hit(self, text: str) -> tuple[bool, str]:
        """Return a selling URL from web search, then from eBay when a token is set."""

        search = self._listing_search
        if search is not None and getattr(search, "enabled", False):
            try:
                found = search.find_listing(text)
            except (OSError, RuntimeError, TypeError, ValueError):
                found = None
            if found is not None:
                return True, str(getattr(found, "url", "") or "")
        checker = self._ebay_checker
        if checker is None or not getattr(checker, "enabled", False):
            return False, ""
        try:
            if hasattr(checker, "match"):
                found = checker.match(text)
                if not found:
                    return False, ""
                flagged, url = found
                return bool(flagged), str(url or "")
            return bool(checker.already_for_sale(text)), ""
        except (OSError, RuntimeError, TypeError, ValueError):
            return False, ""

    def _note_social_progress(self, usage, pair_meta, candidates, reviews, warnings) -> None:
        """Keep the latest drafts and token total so a later error can still fill the page."""

        self._social_usage = usage
        pair = pair_meta or {}
        self._social_preview = {
            "niche_pair_a": pair.get("niche_pair_a", ""),
            "niche_pair_b": pair.get("niche_pair_b", ""),
            "pairing_score": pair.get("pairing_score"),
            "pairing_reason": pair.get("pairing_reason", ""),
            "niche_pair_candidates": [
                item.model_dump(mode="python") if hasattr(item, "model_dump") else item
                for item in pair.get("niche_pair_candidates", [])
            ],
            "line_reviews": [
                item.model_dump(mode="python") if hasattr(item, "model_dump") else item
                for item in reviews
            ],
            "candidates": [
                item.model_dump(mode="python") if hasattr(item, "model_dump") else item
                for item in candidates
            ],
            "stage_warning": " ".join(warning for warning in warnings if warning),
        }

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
            logger.warning(
                "Reddit comment collection skipped: %s Web search will supply source evidence.",
                error,
            )
            return []

    def _humor_selection(self, run: WorkflowRun, input_model):
        """Load references for this run only. The loader itself does not cache rows."""

        from merchandise_discovery.domain.humor_references import HumorReferenceSelection

        if self._humor_reference_loader is None:
            return HumorReferenceSelection(examples=[], themes=[]), []
        references = list(self._humor_reference_loader() or [])
        if not references:
            raise HumorReferenceLoadError(
                "Market references loaded 0 rows. This run stopped instead of inventing demand."
            )
        niches = [
            str(getattr(input_model, "niche_a", "") or ""),
            str(getattr(input_model, "niche_b", "") or ""),
            str(getattr(input_model, "identity", "") or ""),
        ]
        return select_humor_references(references, tone=run.config.humor_tone, niches=niches), references

    def _add_usage(self, current: UsageMetrics, extra: UsageMetrics) -> UsageMetrics:
        """Add a measured call. An empty starting total must not discard the first response."""

        if current.request_count == 0 and current.total_tokens == 0 and current.estimated_cost_usd == 0:
            return extra
        return combine_usage(current, extra)

    def _recent_catalog_terms(self, run: WorkflowRun, limit: int = 40) -> list[str]:
        """Identities and topics from recent runs, so the next sample can avoid a cluster."""

        if self._runs is None:
            return []
        terms: list[str] = []
        for previous_run in self._runs.list_recent(limit=limit):
            if previous_run.run_id == run.run_id:
                continue
            config = previous_run.config
            terms.extend(
                split_identity_names(
                    getattr(config, "social_niche_a", ""),
                    getattr(config, "social_niche_b", ""),
                    getattr(config, "social_identity", ""),
                    getattr(config, "social_query", ""),
                )
            )
            if self._stage_repository is None:
                continue
            previous_stage = self._stage_repository.get_latest(previous_run.run_id, 1)
            output = previous_stage.output_data if previous_stage is not None else {}
            if not isinstance(output, dict):
                continue
            terms.extend(
                split_identity_names(
                    str(output.get("identity_selected") or ""),
                    str(output.get("niche_pair_a") or ""),
                    str(output.get("niche_pair_b") or ""),
                    str(output.get("topic_explored") or ""),
                )
            )
        return terms

    def _atlas_pair_bank(
        self,
        atlas,
        anchor: str,
        avoid: list[str] | None = None,
        trend: dict[str, float] | None = None,
    ) -> list[dict]:
        """Sample broad atlas identities, boosted when they match what is selling."""

        sampled = sample_overlap_pairs(atlas, anchor=anchor, limit=10, avoid=avoid, trend=trend)
        return [
            {"niche_a": item["niche_a"], "niche_b": item["niche_b"]}
            for item in sampled
        ][:12]

    def _score_niche_pairs(self, input_model, bank: list[dict] | None = None, anchor: list[str] | None = None):
        """Score about ten pairs once and keep the best, even when it is under 7."""

        identity = (anchor[0] if anchor else "") or str(getattr(input_model, "identity", "") or "")
        response = self._reasoning_provider.complete_structured(
            system_prompt=(
                "You stack 2 or 3 traits that co-occur in one real person. "
                "Use the supplied atlas bank. Do not invent a job crossed with a hobby, "
                "and do not describe a scenario. Score how truly one person lives the stack, "
                "and how fast a stranger recognizes that person, from 1 to 10."
            ),
            user_prompt=niche_pair_request(identity, bank),
            response_model=NichePairBatch,
            reasoning_effort="low",
        )
        recorded = list(response.output.pairs)
        strong = keep_strong_pairs(recorded)
        ranked = sorted(
            recorded,
            key=lambda pair: (-(pair.shared_life_score + pair.recognizability_score), pair.niche_a),
        )
        best = strong[0] if strong else ranked[0]
        warning = ""
        chosen_a = best.niche_a.strip()
        chosen_b = best.niche_b.strip()
        chosen_reason = best.reason
        chosen_score = round((best.shared_life_score + best.recognizability_score) / 2, 2)
        if bank and not _pair_in_bank(chosen_a, chosen_b, bank):
            chosen_a = str(bank[0]["niche_a"]).strip()
            chosen_b = str(bank[0]["niche_b"]).strip()
            chosen_reason = "Chosen from the identity atlas by buyer pride and broad appeal."
            chosen_score = None
        elif not strong:
            warning = (
                "The best niche pair scored under 7 on shared life or recognizability. "
                "Using it anyway."
            )
        return (
            {
                "niche_pair_a": chosen_a,
                "niche_pair_b": chosen_b,
                "pairing_score": chosen_score,
                "pairing_reason": chosen_reason,
                "niche_pair_candidates": [
                    NichePairRecord(
                        niche_a=pair.niche_a,
                        niche_b=pair.niche_b,
                        shared_life_score=pair.shared_life_score,
                        recognizability_score=pair.recognizability_score,
                        reason=pair.reason,
                        kept=pair.shared_life_score >= 7 and pair.recognizability_score >= 7,
                    )
                    for pair in recorded
                ],
            },
            response.usage,
            warning,
        )

    def _fill_absurd_stacks(
        self,
        run,
        input_model,
        output_model,
        pipeline_module,
        reference_block: str,
        examples: list,
        gold_lines: list[str] | None = None,
        rubric: str = "",
        critic_block: str = "",
    ):
        """One short call for identity-stack lines only. It does not search the web again."""

        niche_a = str(getattr(input_model, "niche_a", "") or "").strip()
        niche_b = str(getattr(input_model, "niche_b", "") or "").strip()
        response = self._reasoning_provider.complete_structured(
            system_prompt=pipeline_module.reasoning_instructions(run.config.humor_tone),
            user_prompt=(
                "Write exactly 2 merchandise lines. pattern must be absurd_identity_stack. "
                f'Build each sincere club name from "{niche_a}" and "{niche_b}". '
                "The traits must genuinely co-occur in one real group. artwork_text is ALL CAPS "
                "and at most 6 words, in a younger register that group would not use about "
                "themselves. A long literal duty list is rejected. Keep it wholesome enough "
                "that a member would buy it. Do not copy an existing slogan. "
                "Use a real reddit.com or x.com source_url already in the evidence you know, "
                "and do not repeat a source sentence as artwork_text.\n"
                f"{reference_block}"
            ),
            response_model=output_model,
            reasoning_effort="low",
        )
        usage = response.usage
        fresh, reviews = self._drop_unoriginal(
            list(getattr(response.output, "candidates", [])),
            examples,
            gold_lines,
        )
        if fresh:
            fresh, critic_usage, critic_rows = self._critic_pass(
                run,
                fresh,
                len(fresh),
                critic_block or reference_block,
                rubric,
            )
            usage = self._add_usage(usage, critic_usage)
            reviews.extend(critic_rows)
        return fresh, usage, reviews

    def _merge_stacks(self, candidates: list, filled: list) -> list:
        """Append new identity-stack lines without duplicating text already kept."""

        seen = {
            str(getattr(candidate, "artwork_text", "") or "").casefold()
            for candidate in candidates
        }
        merged = list(candidates)
        for candidate in filled:
            if not self._is_absurd_stack(candidate):
                continue
            text = str(getattr(candidate, "artwork_text", "") or "").casefold()
            if text and text not in seen:
                merged.append(candidate)
                seen.add(text)
        return merged

    def _without_copied_lines(self, drafted: list, reviews: list) -> list:
        """Do not bring a copied source, reference, or gold line back after the critic."""

        blocked = {
            review.artwork_text
            for review in reviews
            if str(review.reason).startswith("copied")
        }
        return [
            candidate
            for candidate in drafted
            if str(getattr(candidate, "artwork_text", "") or "") not in blocked
        ]

    def _best_available(self, drafted: list, survivors: list, keep_count: int) -> list:
        """Prefer critic survivors, then fill from the original draft so the page is not empty."""

        if len(survivors) >= keep_count:
            return survivors
        seen = {str(getattr(candidate, "artwork_text", "") or "") for candidate in survivors}
        filled = list(survivors)
        for candidate in drafted:
            text = str(getattr(candidate, "artwork_text", "") or "")
            if text in seen:
                continue
            filled.append(candidate)
            seen.add(text)
            if len(filled) >= keep_count:
                break
        return filled or drafted[:keep_count]

    def _is_absurd_stack(self, candidate) -> bool:
        """True when the line is marked as the stacked-club pattern."""

        raw = str(getattr(candidate, "pattern", "") or "")
        normalized = " ".join(raw.casefold().replace("_", " ").replace("-", " ").split())
        return normalized == "absurd identity stack"

    def _wit_is_thin(self, candidates: list) -> bool:
        """A large batch that is mostly identity stacks, not jokes, needs another pass."""

        return len(candidates) >= 6 and primary_wit_share(candidates) < 0.7

    def _spread_is_thin(self, candidates: list) -> bool:
        """A large batch that sits on one pattern or one truth is not a sticker set."""

        if len(candidates) < 6:
            return False
        patterns = {
            str(getattr(candidate, "pattern", "") or "").strip().casefold()
            for candidate in candidates
        }
        truths = {
            " ".join(str(getattr(candidate, "truth", "") or "").casefold().split())
            for candidate in candidates
        }
        patterns.discard("")
        truths.discard("")
        return len(patterns) < 6 or len(truths) < 4

    def _rewrite_for_spread(
        self,
        run,
        input_model,
        output_model,
        pipeline_module,
        reference_block: str,
        examples: list,
        gold_lines: list[str] | None,
        rubric: str,
        critic_block: str = "",
    ):
        """One short rewrite when every line described the same narrow situation."""

        niche_a = str(getattr(input_model, "niche_a", "") or "").strip()
        niche_b = str(getattr(input_model, "niche_b", "") or "").strip()
        response = self._reasoning_provider.complete_structured(
            system_prompt=pipeline_module.reasoning_instructions(run.config.humor_tone),
            user_prompt=(
                "The previous lines all described one narrow policy or incident, "
                "or too few of them were sarcastic, ironic, witty, or puns. "
                "At least 70% of the lines must be sarcastic understatement, "
                "situational or dramatic irony, or a clever reversal. "
                "About 30 to 40 percent must be puns or spoofs. "
                "Each line is a word-and-image pair: set image_idea, why_it_works, and format. "
                "The picture must complete the joke. Text only. Do not generate an image. "
                f"Rewrite {input_model.candidate_count} lines for the broad life of "
                f'"{niche_a}" and "{niche_b}". '
                "Use at least 6 different pattern values and at least 4 different truth values. "
                "Source details are seasoning only. "
                "Set comic_turn to ironic or sarcastic when the line turns. "
                "absurd_identity_stack lines are ALL CAPS and at most 6 words.\n"
                f"{reference_block}"
            ),
            response_model=output_model,
            reasoning_effort="low",
        )
        fresh, reviews = self._drop_unoriginal(
            list(getattr(response.output, "candidates", [])),
            examples,
            gold_lines,
        )
        usage = response.usage
        if fresh:
            fresh, critic_usage, critic_rows = self._critic_pass(
                run,
                fresh,
                len(fresh),
                critic_block or reference_block,
                rubric,
            )
            usage = self._add_usage(usage, critic_usage)
            reviews.extend(critic_rows)
        return fresh, usage, reviews

    def _needs_absurd_stacks(self, candidates: list, keep_count: int) -> bool:
        """Runs that ask for two or more lines must keep two stacked-identity jokes."""

        if keep_count < 2:
            return False
        return sum(1 for candidate in candidates if self._is_absurd_stack(candidate)) < 2

    def _order_with_stacks(self, candidates: list, keep_count: int) -> list:
        """Keep two absurd identity stacks in the returned batch, then the other lines."""

        if keep_count < 2:
            return candidates[:keep_count]
        stacks = [candidate for candidate in candidates if self._is_absurd_stack(candidate)]
        others = [candidate for candidate in candidates if not self._is_absurd_stack(candidate)]
        if len(stacks) < 2:
            return candidates[:keep_count]
        return (stacks[:2] + others + stacks[2:])[:keep_count]

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

    def _drop_unoriginal(
        self,
        candidates: list,
        examples: list,
        gold_lines: list[str] | None = None,
    ) -> tuple[list, list]:
        """Drop lines that quote the source, a reference, or a humor-lab gold line."""

        gold = [line for line in (gold_lines or []) if line.strip()]
        gold_refs = [HumorReference(text=line, upvotes=1, humor_type="gold") for line in gold]
        kept: list = []
        dropped: list = []
        for candidate in candidates:
            text = str(getattr(candidate, "artwork_text", "") or "")
            if gold and (
                copied_from_source(text, *gold) or is_too_similar_to_references(text, gold_refs)
            ):
                dropped.append(
                    LineReviewRecord(
                        artwork_text=text,
                        pattern=str(getattr(candidate, "pattern", "") or ""),
                        funny_score=None,
                        kept=False,
                        reason="copied gold line",
                    )
                )
                continue
            if copied_from_source(
                text,
                str(getattr(candidate, "source_quote", "") or ""),
                str(getattr(candidate, "source_excerpt", "") or ""),
            ):
                dropped.append(
                    LineReviewRecord(
                        artwork_text=text,
                        pattern=str(getattr(candidate, "pattern", "") or ""),
                        funny_score=None,
                        kept=False,
                        reason="copied source",
                    )
                )
                continue
            if is_too_similar_to_references(text, examples):
                dropped.append(
                    LineReviewRecord(
                        artwork_text=text,
                        pattern=str(getattr(candidate, "pattern", "") or ""),
                        funny_score=None,
                        kept=False,
                        reason="copied reference",
                    )
                )
                continue
            kept.append(candidate)
        return kept, dropped

    def _stamp_humor_context(self, output, selection, playbook=None, market=None):
        """Record playbook shapes and the selling signal. Joke lines are not the examples."""

        patterns = (playbook or {}).get("patterns") or []
        identities = list(getattr(market, "identities", []) or [])
        themes = list(getattr(market, "themes", []) or [])
        hooks = list(getattr(market, "hooks", []) or [])
        if not themes and selection is not None:
            themes = [
                " ".join(item.text.replace("(theme)", " ").split())
                for item in getattr(selection, "themes", [])[:10]
                if getattr(item, "is_theme", False)
            ]
        return output.model_copy(
            update={
                "humor_playbook_used": [
                    PlaybookPatternRecord(
                        id=item["id"],
                        label=item["label"],
                        weight=item["weight"],
                    )
                    for item in patterns
                ],
                "humor_examples_used": [],
                "humor_themes_used": themes[:10],
                "market_identities": identities[:12],
                "market_themes": themes[:12],
                "market_hooks": hooks[:12],
                "identity_bucket": getattr(self, "_identity_bucket", "") or "",
                "trending_share": getattr(self, "_trending_share", None),
            }
        )

    def _critic_pass(
        self,
        run: WorkflowRun,
        candidates: list,
        keep_count: int,
        reference_block: str = "",
        rubric: str = "",
    ):
        """Score humor. A member buying the sticker outweighs a generic Reddit score."""

        numbered = "\n".join(
            f"{index}. {getattr(candidate, 'artwork_text', '')} "
            f"(pattern: {getattr(candidate, 'pattern', '')}; "
            f"format: {str(getattr(candidate, 'format', '') or '')[:40]}; "
            f"image idea: {str(getattr(candidate, 'image_idea', '') or '')[:80]}; "
            f"why: {str(getattr(candidate, 'why_it_works', '') or '')[:80]}; "
            f"mechanism: {getattr(candidate, 'humor_mechanism', '')})"
            for index, candidate in enumerate(candidates)
        )
        calibration = ant_calibration_block(
            sample_ant_ratings(load_ant_ratings(), rng=random.Random(run.run_id))
        )
        response = self._reasoning_provider.complete_structured(
            system_prompt=(
                f"{calibration}"
                "You are a merchandise humor critic. "
                "The top question is: is this genuinely witty, sarcastic, or ironic, "
                "and does the target group get it in 2 seconds? "
                "Set word_image_synergy from 1 to 10. The words and the picture are one joke. "
                "A high score means the image completes, flips, or reveals a second meaning. "
                "Score under 7 when the line is just as funny without the picture, or the "
                "picture only illustrates the words. Set literal_image true for that. "
                "Reward a clear pun or spoof the target group gets immediately, including "
                "celebrity_food_pun, brand_logo_spoof, innocent_image_innuendo, "
                "cute_but_menacing, dark_twist_scene, catchphrase_flip, "
                "relatable_confession_action, pop_culture_quote_flip, historical_name_pun, "
                "fake_acronym_org, fake_warning_sign, slogan_twist, rhyme_innuendo, "
                "and holiday_pun. "
                "Raise sticker_buy_score for that pair. "
                "A forced groan or an obscure pun scores at most 4. Set pun_forced true "
                "for a groan and pun_lands false when the group would not get it. "
                "Parody of a famous logo, celebrity, or movie character is allowed. "
                "Mild adult innuendo is allowed. Do not punish either for taste. "
                "Before the scores, set plain_reading to one sentence a random adult would "
                "think the line means. If you cannot, set can_explain false. "
                "Does every word earn its place in the joke? Outside or common words are "
                "allowed when everyone knows them and they serve the setup or the punchline. "
                "Random filler disconnected from the joke scores at most 4. Set "
                "words_earn_their_place false for that filler. "
                "The template 'X is [adj]. My Y isn't.' scores at most 5 unless both halves "
                "are concrete and surprising. "
                "instantly_understandable is required, 1 to 10: can a stranger get the line "
                "in under 2 seconds? Clarity beats cleverness. Score abstract or long "
                "compound club names at 4 or below on instantly_understandable, even if "
                "the wording is inventive. A line under 7 on instantly_understandable is "
                "dropped. The owner calibration above outweighs every instruction below. "
                "The main question is sticker_buy_score, 1 to 10: would a real member of "
                "this group read the line, say 'that's me', and buy it? That score outweighs "
                "reddit_upvote_score. A high Reddit score cannot save a line a member would "
                "not buy. A member who would buy it is not dropped just because Reddit might "
                "not upvote it. Identity stacks must name a real co-occurring group, in a "
                "younger register they would not use about themselves, and stay wholesome. "
                "Score a random word stack, or an absurd_identity_stack longer than 6 words "
                "or not in ALL CAPS, at 4 or below on sticker_buy_score. "
                "Raise sticker_buy_score when comic_turn is ironic or sarcastic and the turn "
                "is clear. Lower it for a straight observation of a policy or rule. "
                "A line that only describes the behavior, with no ironic twist, scores under 7. "
                "If a line needs insider vocabulary a random adult would not know, set "
                "insider_jargon true and cap instantly_understandable and sticker_buy_score "
                "at 5. A universal hook, such as Karen or printer hell, is not insider jargon. "
                "A single tired trope scores at most 6 unless it stacks a second identity "
                "or a fresh twist. Stacking 2 or 3 true traits should score higher. "
                f"{tired_trope_block(load_humor_lab().tired_tropes)}"
                "humor_landed, novelty, and tone_match are 0 to 10. giftability is 0 to 10 "
                "but must not decide the cut when the tone is dark. reddit_upvote_score is "
                "1 to 10 for a generic Reddit upvote. novelty is originality. "
                "Score a line that quotes its source, a reference, or a style example at 4 "
                "or below on sticker_buy_score. Do not reward a copied line.\n"
                f"{rubric}"
            ),
            user_prompt=(
                f"Requested tone: {run.config.humor_tone.value}.\n"
                f"{reference_block}"
                "Score every index once, in this single batch. "
                "sticker_buy_score is 'would a real member say that's me and buy it?'. "
                "It outweighs reddit_upvote_score.\n"
                f"{numbered}"
            ),
            response_model=HumorCritiqueBatch,
            reasoning_effort="low",
        )
        reviews = []
        for review in response.output.reviews:
            text = ""
            if 0 <= review.index < len(candidates):
                text = str(getattr(candidates[review.index], "artwork_text", "") or "")
            row = LineReview(
                index=review.index,
                humor_landed=review.humor_landed,
                novelty=review.novelty,
                tone_match=review.tone_match,
                giftability=review.giftability,
                reddit_upvote_score=review.reddit_upvote_score,
                sticker_buy_score=review.sticker_buy_score,
                instantly_understandable=review.instantly_understandable,
                insider_jargon=review.insider_jargon,
                trait_count=review.trait_count,
                fresh_twist=review.fresh_twist,
                plain_reading=review.plain_reading,
                can_explain=review.can_explain,
                words_earn_their_place=review.words_earn_their_place,
                word_image_synergy=float(getattr(review, "word_image_synergy", 8) or 8),
                pun_lands=getattr(review, "pun_lands", True) is not False,
                pun_forced=bool(getattr(review, "pun_forced", False)),
                literal_image=bool(getattr(review, "literal_image", False)),
            )
            apply_jargon_cap(row, text)
            apply_line_caps(row, text)
            if 0 <= review.index < len(candidates):
                apply_pun_cap(row, candidates[review.index])
            apply_trope_cap(row, text, load_humor_lab().tired_tropes)
            reviews.append(row)
        scored = []
        by_index = {review.index: review for review in reviews}
        for index, candidate in enumerate(candidates):
            review = by_index.get(index)
            score = review.reddit_upvote_score if review is not None else None
            average = critic_average(review) if review is not None else None
            buy = review.sticker_buy_score if review is not None else None
            if (score is None and average is None and buy is None) or not hasattr(candidate, "model_copy"):
                scored.append(candidate)
                continue
            shown = buy if buy is not None else average if average is not None else score
            scored.append(candidate.model_copy(update={"funny_score": shown}))
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
            average = critic_average(review) if review is not None else None
            buy = review.sticker_buy_score if review is not None else None
            if id(candidate) in kept_ids:
                reason, kept_flag = "kept", True
            elif review is not None and getattr(review, "words_earn_their_place", True) is False:
                reason, kept_flag = "doesn't earn its place", False
            elif review is not None and reading_failed(review):
                reason, kept_flag = "unclear", False
            elif review is not None and getattr(review, "filler_contrast", False):
                reason, kept_flag = "filler contrast", False
            elif line_is_pun(candidate) and getattr(review, "pun_forced", False):
                reason, kept_flag = "forced pun", False
            elif line_is_pun(candidate) and getattr(review, "pun_lands", True) is False:
                reason, kept_flag = "obscure pun", False
            elif review is not None and synergy_failed(review):
                reason, kept_flag = "weak word-image pair", False
            elif review is not None and getattr(review, "tired_trope", False):
                reason, kept_flag = "tired trope", False
            elif review is not None and getattr(review, "insider_jargon", False):
                reason, kept_flag = "insider jargon", False
            elif (
                str(getattr(candidate, "comic_turn", "") or "").casefold() == "straight"
                and not line_is_pun(candidate)
            ):
                reason, kept_flag = "no ironic twist", False
            elif member_would_not_buy(review):
                clear = getattr(review, "instantly_understandable", None)
                if clear is not None and float(clear) < 7:
                    reason = "not instantly clear"
                elif buy is not None:
                    reason = "would not buy"
                else:
                    reason = "below 7"
                kept_flag = False
            else:
                reason, kept_flag = "cut by critic", False
            shown = buy if buy is not None else average if average is not None else score
            rows.append(
                LineReviewRecord(
                    artwork_text=str(getattr(candidate, "artwork_text", "") or ""),
                    pattern=str(getattr(candidate, "pattern", "") or ""),
                    funny_score=shown,
                    kept=kept_flag,
                    reason=reason,
                )
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
                    output_data=_social_output_data(output),
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
                    output_data=_social_output_data(output),
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
                    output_data=_social_output_data(output),
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
                    output_data=_social_output_data(output),
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
