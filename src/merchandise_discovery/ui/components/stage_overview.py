"""Human-facing renderers for stage outputs.

The pipeline receives structured stage snapshots, but clients should see decisions and artifacts
in domain language rather than storage-shaped JSON. Each renderer below owns one stage's visual
summary while shared helpers keep spacing, cards, scores, and empty states consistent.
"""

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import streamlit as st

from merchandise_discovery.domain.models.common import IdentityType, StageStatus
from merchandise_discovery.ui.fixtures import StageFixture

PayloadRenderer = Callable[[dict[str, Any]], None]


def _records(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Return only object records from a payload collection so malformed provider data is safe."""

    value = payload.get(key, [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(record: dict[str, Any], *keys: str, default: str = "Not provided") -> str:
    """Read the first useful display value from a serialized stage record."""

    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return default


def _short(value: str, limit: int = 180) -> str:
    """Keep long model/provider text readable in a pipeline card."""

    return value if len(value) <= limit else f"{value[:limit - 1].rstrip()}…"


def _metric_row(values: list[tuple[str, str]]) -> None:
    """Render a compact metric row without requiring every stage to know column layout."""

    if not values:
        return
    columns = st.columns(len(values))
    for column, (label, value) in zip(columns, values):
        column.metric(label, value)


def _section(title: str) -> None:
    """Render the shared subsection label used inside each expanded stage."""

    st.markdown(f"**{title}**")


def _render_humor_references(payload: dict[str, Any]) -> None:
    """Show what is selling. Product wording is not presented as a joke to imitate."""

    identities = payload.get("market_identities") or []
    themes = payload.get("market_themes") or payload.get("humor_themes_used") or []
    hooks = payload.get("market_hooks") or []
    if not identities and not themes and not hooks:
        return
    _section("What's selling")
    st.caption(
        "Trending buyers are who is buying merch right now. "
        "Themes are secondary. Product wording is not a joke to copy."
    )
    if identities:
        st.write("Trending buyers: " + " · ".join(str(item) for item in identities[:12]))
    if themes:
        st.write("Themes: " + " · ".join(str(item) for item in themes[:12]))
    if hooks:
        st.write("Hooks: " + " · ".join(str(item) for item in hooks[:12]))


def _render_playbook(payload: dict[str, Any]) -> None:
    """Show the shapes the writer was told to use, highest priority first."""

    patterns = payload.get("humor_playbook_used") or []
    if not patterns:
        return
    _section("Humor playbook")
    st.caption("Structures for this run. The writer was told not to copy sample wording.")
    for item in patterns:
        if not isinstance(item, dict):
            continue
        weight = item.get("weight")
        weight_text = f", weight {weight}" if weight else ""
        st.write(f"- {item.get('label') or item.get('id')}{weight_text}")


def _render_shop_fields(candidate: dict) -> None:
    """Show the categorizer fields for one final line."""

    if candidate.get("main_category"):
        st.caption(f"Category: {candidate['main_category']}")
    secondary = candidate.get("secondary_categories") or []
    if secondary:
        st.caption("Also: " + " · ".join(str(item) for item in secondary))
    tags = candidate.get("tags") or []
    if tags:
        st.caption("Tags: " + ", ".join(str(item) for item in tags))
    if candidate.get("website_title"):
        st.caption(f"Website title: {candidate['website_title']}")
    if candidate.get("ebay_title"):
        st.caption(f"eBay title: {candidate['ebay_title']}")
    if candidate.get("slug"):
        st.caption(f"Slug: {candidate['slug']}")


def _who_label(labels: object) -> str:
    """Join 2 to 4 buyer categories for the run page and the line export."""

    if not isinstance(labels, list):
        return ""
    return " · ".join(str(item) for item in labels if str(item).strip())


def _render_line_reviews(payload: dict[str, Any]) -> None:
    """Show the Reddit-upvote critic: kept lines, dropped lines, and why."""

    reviews = payload.get("line_reviews") or []
    if not reviews:
        return
    _section("Humor critic")
    st.caption("Lines under 7, or lines copied from the source or a reference, are dropped.")
    for item in reviews:
        if not isinstance(item, dict):
            continue
        status = "kept" if item.get("kept") else "dropped"
        score = item.get("funny_score")
        score_text = f"{score}/10" if score is not None else "unscored"
        reason = item.get("reason") or "unspecified"
        pattern = item.get("pattern") or "unspecified"
        text = item.get("artwork_text") or "(empty)"
        buyers = _who_label(item.get("who_its_for"))
        st.write(f"- {status} ({score_text}, {pattern}, {reason}): {text}")
        if buyers:
            st.caption(f"Who it's for: {buyers}")


def _render_social_behavior_text(
    payload: dict[str, Any],
    input_payload: dict[str, Any] | None = None,
) -> None:
    """Show either social A/B variant with its source request and audience context."""

    if payload.get("stage_warning"):
        st.warning(str(payload["stage_warning"]))
    candidates = _records(payload, "candidates")
    request = input_payload or {}
    sources = request.get("sources", [])
    source_names = ", ".join(str(source).title() for source in sources) if sources else "Not recorded"
    query = str(request.get("query") or payload.get("topic_explored") or "Not recorded")
    _section("Run input")
    _metric_row([
        ("Sources", source_names),
        ("Requested candidates", str(request.get("candidate_count", "Not recorded"))),
    ])
    selected_identity = request.get("identity") or payload.get("identity_selected")
    identity_type = request.get("identity_type") or payload.get("identity_type_selected", "other")
    identity_type_value = getattr(identity_type, "value", identity_type)
    if selected_identity:
        st.write(
            f"**Target identity:** {selected_identity} "
            f"({str(identity_type_value).replace('_', ' ').title()})"
        )
    if request.get("auto_identity"):
        st.caption("Identity and identity type selected by AI from the searched discussions.")
    niche_a = str(request.get("niche_a") or "").strip()
    niche_b = str(request.get("niche_b") or "").strip()
    pair_a = str(payload.get("niche_pair_a") or niche_a).strip()
    pair_b = str(payload.get("niche_pair_b") or niche_b).strip()
    loaded = payload.get("atlas_subgroups_loaded")
    if loaded is None:
        from merchandise_discovery.infrastructure.identity_atlas_loader import load_identity_atlas

        loaded = len(load_identity_atlas().subgroups)
    st.caption(f"atlas: {int(loaded)} subgroups loaded")
    bucket = str(payload.get("identity_bucket") or "").strip()
    if bucket:
        share = payload.get("trending_share")
        share_text = f" ({float(share):.0%} trending)" if isinstance(share, (int, float)) else ""
        st.caption(f"Identity pick: {bucket}{share_text}")
    if pair_a and pair_b:
        score = payload.get("pairing_score")
        score_text = f" (pairing score {score}/10)" if score is not None else ""
        st.write(f"**Niche crossover:** {pair_a} × {pair_b}{score_text}")
        if payload.get("pairing_reason"):
            st.caption(str(payload["pairing_reason"]))
    _render_humor_references(payload)
    _render_playbook(payload)
    _render_line_reviews(payload)
    if request.get("auto_topic"):
        st.write(f"**Behavior or topic selected by AI:** {query}")
    else:
        st.write(f"**Behavior or topic explored:** {query}")
    _metric_row([
        ("Text candidates", str(len(candidates))),
        ("Search summary", "Available" if payload.get("search_summary") else "Not available"),
    ])
    if payload.get("search_summary"):
        st.caption(_short(str(payload["search_summary"]), 300))

    dossier = payload.get("dossier")
    if isinstance(dossier, dict):
        _section("Identity dossier")
        _metric_row(
            [
                ("Insider language", str(len(dossier.get("insider_language", [])))),
                ("Artifacts or rituals", str(len(dossier.get("work_artifacts_or_rituals", [])))),
                ("Source records", str(len(dossier.get("evidence", [])))),
            ]
        )
        with st.expander("Identity signals used by the writer", expanded=False):
            st.write(
                "**Insider language:** "
                + " · ".join(str(item) for item in dossier.get("insider_language", []))
            )
            st.write(
                "**Work artifacts or rituals:** "
                + " · ".join(str(item) for item in dossier.get("work_artifacts_or_rituals", []))
            )
            st.write(
                "**Identity-specific tensions:** "
                + " · ".join(str(item) for item in dossier.get("identity_specific_tensions", []))
            )
        with st.expander("Dossier evidence", expanded=False):
            for evidence in _records(dossier, "evidence"):
                title = _text(evidence, "source_title", default="Source")
                url = _text(evidence, "source_url", default="")
                st.markdown(f"[{title}]({url})" if url else f"**{title}**")
                st.caption(_text(evidence, "source_excerpt"))

    if candidates:
        st.download_button(
            "Download text candidates",
            data=json.dumps(
                {
                    "candidates": [
                        {
                            "artwork_text": candidate.get("artwork_text", ""),
                            "image_idea": candidate.get("image_idea", ""),
                            "why_it_works": candidate.get("why_it_works", ""),
                            "format": candidate.get("format", ""),
                            "who_its_for": candidate.get("who_its_for") or [],
                            "pattern": candidate.get("pattern", ""),
                            "truth": candidate.get("truth", ""),
                            "comic_turn": candidate.get("comic_turn", ""),
                            "funny_score": candidate.get("funny_score"),
                            "main_category": candidate.get("main_category", ""),
                            "secondary_categories": candidate.get("secondary_categories") or [],
                            "tags": candidate.get("tags") or [],
                            "website_title": candidate.get("website_title", ""),
                            "ebay_title": candidate.get("ebay_title", ""),
                            "slug": candidate.get("slug", ""),
                            "identity_bucket": candidate.get("identity_bucket", ""),
                        }
                        for candidate in candidates
                    ],
                    "line_reviews": payload.get("line_reviews") or [],
                },
                indent=2,
            ),
            file_name="sticker-lines.json",
            mime="application/json",
            key="export-sticker-lines",
        )
    for index, candidate in enumerate(candidates, start=1):
        st.markdown(
            f"### {index}. {_text(candidate, 'artwork_text', default='Image only')}"
        )
        image_idea = str(candidate.get("image_idea") or "").strip()
        if image_idea:
            st.caption(f"Image idea: {image_idea}")
        why_it_works = str(candidate.get("why_it_works") or "").strip()
        if why_it_works:
            st.caption(f"Why it works: {why_it_works}")
        sticker_format = str(candidate.get("format") or "").strip()
        if sticker_format:
            st.caption(f"Format: {sticker_format}")
        if candidate.get("source_quote"):
            st.caption(f"Quote: {_text(candidate, 'source_quote')}")
        funny_score = candidate.get("funny_score")
        if funny_score is not None:
            st.caption(f"Funny score: {funny_score} / 10")
        if candidate.get("pattern"):
            st.caption(f"Pattern: {_text(candidate, 'pattern')}")
        buyers = _who_label(candidate.get("who_its_for"))
        if buyers:
            st.caption(f"Who it's for: {buyers}")
        _render_shop_fields(candidate)
        if candidate.get("humor_mechanism") or candidate.get("concrete_detail"):
            st.caption(
                "Humor: "
                f"{_text(candidate, 'humor_mechanism', default='unspecified')} · "
                f"{_text(candidate, 'concrete_detail', default='no detail')}"
            )
        if candidate.get("identity"):
            identity_type = _text(candidate, "identity_type", default="other")
            try:
                identity_type_label = IdentityType(identity_type).display_name
            except ValueError:
                identity_type_label = identity_type.replace("_", " ").title()
            st.markdown(
                f"**Audience identified for this behavior:** {_text(candidate, 'identity')} "
                f"({identity_type_label})"
            )
            st.caption(f"Why this audience fits: {_text(candidate, 'identity_evidence')}")
        with st.expander("Grok artwork prompt", expanded=False):
            st.code(_text(candidate, "artwork_prompt"), language="text")
        with st.expander("Visual direction", expanded=False):
            st.write(f"**Visual punchline:** {_text(candidate, 'visual_punchline')}")
            st.write(f"**Main visual metaphor:** {_text(candidate, 'main_visual_metaphor')}")
            st.write(f"**Audience-specific cue:** {_text(candidate, 'audience_specific_cue')}")
            st.write(f"**Tone:** {_text(candidate, 'tone')}")
            st.write(f"**Style:** {_text(candidate, 'style_direction')}")
            avoid = candidate.get("things_to_avoid", [])
            if avoid:
                st.caption("Avoid: " + " · ".join(str(item) for item in avoid))
        st.markdown("**Observed behavior**")
        st.write(_text(candidate, "behavior"))
        st.markdown("**Friction or pressure**")
        st.write(_text(candidate, "friction_or_pressure", "identity_specific_tension"))
        st.markdown("**Why this is specific**")
        st.write(_text(candidate, "specificity_reason", "identity_recognition_reason"))
        source_url = _text(candidate, "source_url", default="")
        source_title = _text(candidate, "source_title", default="Source")
        if source_url:
            st.markdown(f"Source: [{source_title}]({source_url})")
        with st.expander("Source evidence", expanded=False):
            st.caption(_text(candidate, "source_excerpt"))


def _render_seed_discovery(payload: dict[str, Any]) -> None:
    """Show the Stage 1 decision summary without turning the pipeline card into a transcript."""

    seeds = _records(payload, "selected_seeds")

    category_counts = {
        category: sum(
            _text(seed, "category", default="Unknown").lower() == category
            for seed in seeds
        )
        for category in ("audience", "interest", "value")
    }
    _metric_row([
        ("Audience selected", str(category_counts["audience"])),
        ("Interest selected", str(category_counts["interest"])),
        ("Value selected", str(category_counts["value"])),
    ])
    _metric_row([
        ("Selection seed", str(payload.get("selection_seed", "Not recorded"))),
        ("Total selected", str(len(seeds))),
    ])

    _section("Selected seed groups")
    rows = []
    for seed in seeds:
        rows.append(
            {
                "Category": _text(seed, "category", default="Unknown").title(),
                "Seed group": _text(seed, "name"),
            }
        )
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")


def _render_identity_expansion(payload: dict[str, Any]) -> None:
    """Render expanded identity dimensions as a compact, inspectable Stage 2 result table."""

    identities = _records(payload, "identities")
    provider_count = sum(identity.get("provenance") == "provider" for identity in identities)
    _metric_row([
        ("Expanded dimensions", str(len(identities))),
        ("Provider-generated", str(provider_count)),
    ])
    summary = payload.get("summary")
    if summary:
        st.caption(f"Provider summary: {_short(str(summary), 240)}")

    _section("Identity dimensions")
    rows = []
    for identity in identities:
        confidence = identity.get("confidence")
        relevance = identity.get("merchandise_relevance")
        rows.append(
            {
                "Type": _text(identity, "dimension_type").title(),
                "Dimension": _text(identity, "value"),
                "Source seed": _text(identity, "source_seed_name"),
                "Confidence": f"{float(confidence):.0%}" if confidence is not None else "—",
                "Merchandise relevance": str(relevance) if relevance is not None else "—",
            }
        )
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")


def _render_intersections(payload: dict[str, Any]) -> None:
    intersections = _records(payload, "intersections")
    provider_count = payload.get("provider_proposals_count")
    rejected_count = payload.get("provider_rejected_count")
    metrics = [("Candidate intersections", str(len(intersections)))]
    if provider_count:
        metrics.append(("AI proposals", str(provider_count)))
        if rejected_count:
            metrics.append(("Rejected by system", str(rejected_count)))
    _metric_row(metrics)
    summary = payload.get("summary")
    if summary:
        st.caption(str(summary))
    _section("Candidate combinations")
    rows = [
        {
            "Identities": " + ".join(str(item) for item in record.get("identities", [])),
            "Why this combination": str(record.get("metadata", {}).get("composition_rationale", "—")),
            "Distinctiveness": record.get("metadata", {}).get("distinctiveness", "—"),
            "Candidate ID": _text(record, "intersection_id"),
        }
        for record in intersections
    ]
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")


def _render_coherence(payload: dict[str, Any]) -> None:
    intersections = _records(payload, "intersections")
    selected_ids = {str(item) for item in payload.get("selected_intersection_ids", [])}
    selected = [item for item in intersections if item.get("intersection_id") in selected_ids]
    _metric_row([
        ("Candidates reviewed", str(len(intersections))),
        ("Selected for research", str(len(selected))),
    ])
    summary = payload.get("summary")
    if summary:
        st.caption(str(summary))
    _section("AI-selected research candidates")
    # Stage 4 now displays the AI decision and its reason; it does not imply that a later
    # deterministic ranking silently removed the remaining candidates.
    for record in selected:
        metadata = record.get("metadata", {})
        with st.container(border=True):
            st.markdown(f"**{' + '.join(str(item) for item in record.get('identities', []))}**")
            score = float(record.get("coherence_score") or 0)
            st.progress(min(1.0, score / 10), text=f"Coherence {score:.1f} / 10")
            confidence = metadata.get("coherence_confidence")
            if confidence is not None:
                confidence = max(0.0, min(1.0, float(confidence)))
                st.progress(
                    confidence,
                    text=f"Confidence {confidence:.2f} / 1.00 ({confidence:.0%})",
                )
            st.write(f"**Why selected:** {metadata.get('selection_reason', '—')}")
            st.caption(
                f"Research value: {float(metadata.get('research_value_score', 0)):.1f} / 10"
            )
    _section("Not selected")
    for record in intersections:
        if record.get("intersection_id") in selected_ids:
            continue
        st.caption(
            f"{' + '.join(str(item) for item in record.get('identities', []))} · "
            f"{_text(record, 'filter_reason', default='Not selected by AI for this research budget.')}"
        )


def _render_filter(payload: dict[str, Any]) -> None:
    accepted = _records(payload, "accepted")
    rejected = _records(payload, "rejected")
    _metric_row([("Accepted", str(len(accepted))), ("Rejected", str(len(rejected)))])
    left, right = st.columns(2)
    with left:
        _section("Accepted for research")
        for record in accepted[:8]:
            st.success(" + ".join(str(item) for item in record.get("identities", [])))
    with right:
        _section("Filtered out")
        for record in rejected[:8]:
            st.warning(
                f"{' + '.join(str(item) for item in record.get('identities', []))}\n\n"
                f"{_text(record, 'filter_reason')}"
            )


def _render_research(payload: dict[str, Any]) -> None:
    niches = _records(payload, "niches")
    evidence = _records(payload, "evidence")
    concepts = _records(payload, "concepts")
    metrics = [("Niches researched", str(len(niches))), ("Evidence records", str(len(evidence)))]
    if concepts:
        metrics.append(("Concepts generated", str(len(concepts))))
    _metric_row(metrics)
    if evidence:
        _section("Research evidence")
        evidence_by_niche: dict[str, list[dict[str, Any]]] = {}
        for item in evidence:
            evidence_by_niche.setdefault(str(item.get("niche_id", "")), []).append(item)

        # Grouping sources by niche keeps the causal story visible: the client can open one niche,
        # inspect every supporting record, and then move to the next without scanning a wide table.
        rendered_evidence_ids: set[int] = set()
        for niche in niches:
            niche_id = str(niche.get("niche_id", ""))
            niche_evidence = evidence_by_niche.get(niche_id, [])
            with st.expander(
                f"{_text(niche, 'name')} · {len(niche_evidence)} evidence records",
                expanded=False,
            ):
                if not niche_evidence:
                    st.caption("No evidence records were persisted for this niche.")
                    continue
                for item in niche_evidence:
                    rendered_evidence_ids.add(id(item))
                    title = _text(item, "title")
                    url = _text(item, "url", default="")
                    st.markdown(f"[{title}]({url})" if url else f"**{title}**")
                    st.caption(
                        f"{_text(item, 'source', default='Unknown source')} · "
                        f"{_text(item, 'evidence_type', default='public_web')}"
                    )
                    st.write(_text(item, "excerpt"))
                    st.divider()

        unassigned = [item for item in evidence if id(item) not in rendered_evidence_ids]
        if unassigned:
            with st.expander(f"Unassigned evidence · {len(unassigned)} records", expanded=False):
                for item in unassigned:
                    title = _text(item, "title")
                    url = _text(item, "url", default="")
                    st.markdown(f"[{title}]({url})" if url else f"**{title}**")
                    st.caption(_text(item, "source", default="Unknown source"))
                    st.write(_text(item, "excerpt"))
    if concepts:
        _section("Evidence-backed concepts")
        for concept in concepts:
            with st.container(border=True):
                st.markdown(f"**{_text(concept, 'phrase')}**")
                st.caption(_text(concept, "specific_audience"))
                st.write(_short(_text(concept, "description")))
                st.caption(f"Recognizable moment: {_text(concept, 'recognizable_moment')}")


def _render_experience_mining(payload: dict[str, Any]) -> None:
    signals = _records(payload, "signals")
    _metric_row([("Niches with signals", str(len(signals)))])
    for signal in signals:
        with st.container(border=True):
            st.markdown(f"**Niche {_text(signal, 'niche_id')}**")
            confidence = float(signal.get("confidence") or 0)
            st.progress(confidence, text=f"Evidence confidence {confidence:.0%}")
            for label, key in (
                ("Repeated language", "repeated_language"),
                ("Frustrations", "frustrations"),
                ("Rituals", "rituals"),
                ("Emotional signals", "emotional_signals"),
            ):
                values = signal.get(key, [])
                if isinstance(values, list) and values:
                    st.caption(label)
                    st.write(" · ".join(str(value) for value in values))
            st.info(_text(signal, "experience_summary"))


def _render_opportunity_scoring(payload: dict[str, Any]) -> None:
    scores = _records(payload, "scores")
    _metric_row([("Niches scored", str(len(scores)))])
    for score in scores:
        with st.container(border=True):
            st.markdown(f"**Niche {_text(score, 'niche_id')}**")
            overall = float(score.get("overall_score") or 0)
            st.progress(overall / 100, text=f"Opportunity score {overall:.1f} / 100")
            _metric_row(
                [
                    ("Evidence", f"{float(score.get('evidence_strength') or 0):.1f}"),
                    ("Clarity", f"{float(score.get('experience_clarity') or 0):.1f}"),
                    ("Audience fit", f"{float(score.get('audience_fit') or 0):.1f}"),
                    ("Differentiation", f"{float(score.get('differentiation') or 0):.1f}"),
                ]
            )
            st.caption(_text(score, "rationale"))


def _render_concepts(payload: dict[str, Any]) -> None:
    concepts = _records(payload, "concepts")
    rejected = _records(payload, "rejected_proposals")
    metrics = [("Specific concepts", str(len(concepts)))]
    if payload.get("provider_proposals_count") is not None:
        metrics.append(("AI proposals", str(payload.get("provider_proposals_count", 0))))
    metrics.append(("Rejected as generic", str(len(rejected))))
    _metric_row(metrics)
    if payload.get("summary"):
        st.caption(str(payload["summary"]))
    for concept in concepts:
        with st.container(border=True):
            st.markdown(f"**{_text(concept, 'phrase')}**")
            _metric_row(
                [
                    ("Specificity", f"{float(concept.get('specificity_score') or 0):.1f} / 10"),
                    ("Audience", _short(_text(concept, "specific_audience"), 70)),
                ]
            )
            st.write(_short(_text(concept, "description")))
            st.caption(f"Recognizable moment: {_text(concept, 'recognizable_moment')}")
            st.caption(f"Visual hook: {_text(concept, 'visual_hook')}")
            if concept.get("overall_score") is not None:
                st.progress(float(concept["overall_score"]) / 10, text=f"Score {float(concept['overall_score']):.1f} / 10")


def _render_critique(payload: dict[str, Any]) -> None:
    evaluations = _records(payload, "evaluations")
    kept = sum(_text(item, "verdict", default="reject") == "keep" for item in evaluations)
    _metric_row([("Reviewed", str(len(evaluations))), ("Kept", str(kept))])
    for evaluation in evaluations:
        with st.container(border=True):
            verdict = _text(evaluation, "verdict", default="pending").upper()
            st.markdown(f"**{_text(evaluation, 'concept_id')}** · {verdict}")
            _metric_row(
                [
                    ("Authenticity", f"{float(evaluation.get('authenticity') or 0):.1f}"),
                    ("Clarity", f"{float(evaluation.get('clarity') or 0):.1f}"),
                    ("Wearability", f"{float(evaluation.get('wearability') or 0):.1f}"),
                    ("Commercial", f"{float(evaluation.get('commercial_potential') or 0):.1f}"),
                    ("Recognition", f"{float(evaluation.get('personal_recognition') or 0):.1f}"),
                    ("Specificity", f"{float(evaluation.get('niche_specificity') or 0):.1f}"),
                ]
            )
            weaknesses = evaluation.get("weaknesses", [])
            if weaknesses:
                st.warning(" · ".join(str(item) for item in weaknesses))


def _render_similarity(payload: dict[str, Any]) -> None:
    checks = _records(payload, "checks")
    survivors = _records(payload, "survivors")
    rejected = _records(payload, "rejected")
    _metric_row([("Screened", str(len(checks))), ("Survivors", str(len(survivors))), ("Rejected", str(len(rejected)))])
    for check in checks:
        risk = _text(check, "risk_level", default="unknown").upper()
        if risk == "HIGH":
            st.error(f"{_text(check, 'concept_id')}: {_text(check, 'reason')}")
        else:
            st.success(f"{_text(check, 'concept_id')}: no duplicate found")


def _render_selection(payload: dict[str, Any]) -> None:
    finalists = _records(payload, "finalists")
    rejected = _records(payload, "rejected")
    evaluations = {
        item.get("concept_id"): item for item in _records(payload, "evaluations")
    }
    metrics = [("Finalists", str(len(finalists))), ("Not selected", str(len(rejected)))]
    if evaluations:
        metrics.append(("AI comparisons", str(len(evaluations))))
    _metric_row(metrics)
    _section("Selected finalists")
    for finalist in finalists:
        with st.container(border=True):
            st.markdown(f"**#{_text(finalist, 'rank')} · {_text(finalist, 'phrase')}**")
            score = finalist.get("selection_score", finalist.get("overall_score"))
            st.caption(f"Final selection score {float(score or 0):.1f} / 10")
            st.write(_short(_text(finalist, "description")))
            evaluation = evaluations.get(finalist.get("concept_id"))
            if evaluation and evaluation.get("rationale"):
                st.caption(f"Comparison rationale: {_short(str(evaluation['rationale']), 220)}")


def _render_briefs(payload: dict[str, Any]) -> None:
    briefs = _records(payload, "briefs")
    _metric_row([("Design briefs", str(len(briefs)))])
    for brief in briefs:
        with st.container(border=True):
            st.markdown(f"**Exact phrase: {_text(brief, 'exact_phrase')}**")
            st.caption(_text(brief, "target_audience"))
            _metric_row(
                [
                    ("Subject", _short(_text(brief, "main_subject"), 70)),
                    ("Style", _short(_text(brief, "illustration_style"), 70)),
                    ("Merchandise", _short(_text(brief, "intended_merchandise_type"), 70)),
                ]
            )
            st.write(_text(brief, "composition"))
            st.caption(f"Core concept: {_text(brief, 'core_concept')}")
            st.caption(f"Detail level: {_text(brief, 'detail_level')}")
            constraints = brief.get("constraints", [])
            avoid = brief.get("things_to_avoid", [])
            if constraints or avoid:
                st.caption(
                    "Constraints and avoid list: "
                    + " · ".join(str(item) for item in [*constraints, *avoid])
                )


def _render_prompts(payload: dict[str, Any]) -> None:
    prompts = _records(payload, "prompts")
    _metric_row([("Prompts compiled", str(len(prompts)))])
    for prompt in prompts:
        with st.container(border=True):
            st.markdown(f"**Concept {_text(prompt, 'concept_id')}**")
            st.code(_text(prompt, "prompt"), language="text")


def _render_artwork_generation(payload: dict[str, Any]) -> None:
    """Render the finished stickers in one row, then any extras as cards."""

    artworks = _records(payload, "artworks")
    _metric_row([("Artwork candidates", str(len(artworks)))])
    if artworks:
        _render_sticker_grid(artworks[:5])
        if len(artworks) > 5:
            _render_artwork_cards(artworks[5:], "Generated artwork")
    else:
        st.caption("No artwork images were generated.")


def _render_sticker_grid(artworks: list[dict[str, Any]]) -> None:
    """Show up to five finished stickers with the line, the buyer, and a download."""

    columns = st.columns(len(artworks))
    for column, artwork in zip(columns, artworks):
        with column:
            text = _text(artwork, "combination_name", default="Sticker")
            st.markdown(f"**{text}**")
            buyers = ""
            critique = artwork.get("critique") or {}
            if isinstance(critique, dict):
                buyers = str(critique.get("who_its_for") or "")
            if buyers:
                st.caption(f"Who it's for: {buyers}")
            _render_artwork_image(artwork, text)
            source = _artwork_source(artwork)
            path = Path(source) if source else None
            if path is not None and path.is_file():
                st.download_button(
                    "Download",
                    data=path.read_bytes(),
                    file_name=f"{path.stem}.png",
                    mime="image/png",
                    key=f"download-{artwork.get('artwork_id', path.name)}",
                )
def _artwork_source(record: dict[str, Any]) -> str:
    """Prefer the durable local artifact and fall back to the provider reference URL."""

    storage_key = record.get("storage_key")
    if storage_key:
        root = Path(os.getenv("ARTWORK_STORAGE_DIR", ".artifacts")).resolve()
        candidate = (root / str(storage_key)).resolve()
        try:
            if candidate.is_file() and candidate.is_relative_to(root):
                return str(candidate)
        except (OSError, ValueError):
            # A missing or malformed local artifact should not hide a usable provider URL.
            pass
    return str(record.get("source_url") or "")


def _artwork_result_groups(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Group final images as accepted, regenerated, or hard-rejected.

    Stage 17 deliberately keeps rejected artwork in its output. A missing evaluation is treated as
    non-rejected for historical gallery snapshots, because silently hiding a legacy image would make
    before/after comparisons impossible.
    """

    artworks = _records(payload, "artworks")
    evaluations = {
        str(item.get("artwork_id")): item for item in _records(payload, "evaluations")
    }
    accepted: list[dict[str, Any]] = []
    regenerated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for artwork in artworks:
        artwork_id = str(artwork.get("artwork_id", ""))
        evaluation = evaluations.get(artwork_id, {})
        decision = str(evaluation.get("decision") or artwork.get("decision") or "").lower()
        if decision == "reject":
            rejected.append(artwork)
        elif decision == "regenerate":
            regenerated.append(artwork)
        else:
            accepted.append(artwork)
    return accepted, regenerated, rejected


def _render_artwork_cards(artworks: list[dict[str, Any]], category: str) -> None:
    """Render one image category using the shared comparison card layout."""

    for index in range(0, len(artworks), 2):
        columns = st.columns(2)
        for column, artwork in zip(columns, artworks[index : index + 2]):
            with column:
                st.markdown(
                    f"**{_text(artwork, 'combination_name', 'phrase', default='Artwork candidate')}**"
                )
                st.caption(
                    f"Candidate ID: {_text(artwork, 'artwork_id')} · "
                    f"Concept ID: {_text(artwork, 'concept_id')}"
                )
                with st.expander("Artwork generation prompt"):
                    st.code(_text(artwork, "prompt"), language="text")
                _render_artwork_image(
                    artwork,
                    str(artwork.get("_image_caption") or "Die-cut sticker"),
                )
                raw_key = artwork.get("raw_storage_key")
                if raw_key:
                    with st.expander("Original generation"):
                        _render_artwork_image(
                            {"storage_key": raw_key},
                            "Original before die-cut",
                        )
                st.caption(
                    f"{_text(artwork, 'mime_type', default='Unknown format')} · "
                    f"{_text(artwork, 'width')} × {_text(artwork, 'height')}"
                )
                url = _text(artwork, "source_url", default="")
                if url:
                    st.markdown(f"[Open provider reference]({url})")
                st.caption(category)


def _render_artwork_image(artwork: dict[str, Any], caption: str) -> None:
    """Render one artwork reference with a consistent unavailable-image state."""

    source = _artwork_source(artwork)
    if source:
        try:
            st.image(source, caption=caption, width=420)
        except (OSError, RuntimeError, ValueError):
            st.warning("The artwork preview is unavailable.")
    else:
        st.info("No preview reference was recorded for this artwork.")


def _render_regenerated_comparisons(
    regenerated: list[dict[str, Any]],
    originals: list[dict[str, Any]],
) -> None:
    """Show each regenerated candidate as an explicit original-versus-revised pair."""

    originals_by_id = {
        str(item.get("artwork_id")): item for item in originals
    }
    for artwork in regenerated:
        artwork_id = str(artwork.get("artwork_id", ""))
        original = originals_by_id.get(artwork_id)
        with st.container(border=True):
            st.markdown(
                f"**{_text(artwork, 'combination_name', 'phrase', default='Artwork candidate')}**"
            )
            st.caption(f"Candidate ID: {_text(artwork, 'artwork_id')}")
            with st.expander("Artwork generation prompt"):
                st.code(_text(artwork, "prompt"), language="text")
            if original is None:
                st.warning("The original image reference is unavailable for this candidate.")
                _render_artwork_image(artwork, "Revised by Grok")
                continue
            original_column, revised_column = st.columns(2)
            with original_column:
                _render_artwork_image(original, "Original")
            with revised_column:
                _render_artwork_image(artwork, "Revised by Grok")
            st.caption(
                f"Original: {_text(original, 'mime_type', default='Unknown format')} · "
                f"{_text(original, 'width')} × {_text(original, 'height')}  |  "
                f"Revised: {_text(artwork, 'mime_type', default='Unknown format')} · "
                f"{_text(artwork, 'width')} × {_text(artwork, 'height')}"
            )


def _original_artwork_records(
    artworks: list[dict[str, Any]],
    revisions: list[dict[str, Any]],
    explicit_originals: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Rebuild original image references from revision audit records for the comparison section.

    Older final-stage payloads predate original-reference persistence. For those records, the
    current artwork is the only available representation and is returned unchanged rather than
    displaying a misleading blank image.
    """

    explicit_by_id = {
        str(item.get("artwork_id")): item for item in (explicit_originals or [])
    }
    revisions_by_id = {
        str(item.get("artwork_id")): item for item in revisions
    }
    originals: list[dict[str, Any]] = []
    for artwork in artworks:
        explicit_original = explicit_by_id.get(str(artwork.get("artwork_id", "")))
        if explicit_original is not None:
            original = dict(explicit_original)
            original["_image_caption"] = "Original artwork"
            originals.append(original)
            continue
        revision = revisions_by_id.get(str(artwork.get("artwork_id", "")))
        if not revision or not any(key in revision for key in (
            "original_source_url",
            "original_storage_key",
        )):
            original = dict(artwork)
            original["_image_caption"] = "Original reference unavailable"
        else:
            original = {
                **artwork,
                "source_url": revision.get("original_source_url"),
                "storage_key": revision.get("original_storage_key"),
                "width": revision.get("original_width"),
                "height": revision.get("original_height"),
                "mime_type": revision.get("original_mime_type"),
                "file_size_bytes": revision.get("original_file_size_bytes"),
            }
            original["_image_caption"] = "Original artwork"
        originals.append(original)
    return originals


def _render_artwork_gallery(payload: dict[str, Any]) -> None:
    """Display the accepted-versus-regenerated comparison from the final results stage."""

    accepted, regenerated, rejected = _artwork_result_groups(payload)
    original_artworks = _original_artwork_records(
        _records(payload, "artworks"),
        _records(payload, "revisions"),
        _records(payload, "original_artworks"),
    )
    _metric_row(
        [
            ("Accepted", str(len(accepted))),
            ("Regenerated", str(len(regenerated))),
            ("Artwork results", str(len(accepted) + len(regenerated) + len(rejected))),
        ]
    )
    if not accepted and not regenerated and not rejected:
        st.info("No artwork candidates are available yet.")
        return

    st.subheader(f"Accepted · {len(accepted)}")
    if accepted:
        _render_artwork_cards(accepted, "Accepted by Luna")
    else:
        st.caption("No artwork was accepted without edits.")

    # Hard rejection is distinct from regeneration. It is uncommon, but if Luna returns one we
    # show it separately rather than incorrectly claiming that it was edited by Grok.
    if rejected:
        st.subheader(f"Rejected · {len(rejected)}")
        _render_artwork_cards(rejected, "Rejected by Luna; not regenerated")

    st.subheader(f"Regenerated · {len(regenerated)}")
    if regenerated:
        _render_regenerated_comparisons(regenerated, original_artworks)
    else:
        st.caption("No artwork was sent for regeneration.")


def _render_artwork_critique(payload: dict[str, Any]) -> None:
    evaluations = _records(payload, "evaluations")
    accepted = sum(_text(item, "decision", default="") == "accept" for item in evaluations)
    _metric_row([("QA checked", str(len(evaluations))), ("Passed", str(accepted))])
    for evaluation in evaluations:
        with st.container(border=True):
            decision = _text(evaluation, "decision", default="pending").upper()
            st.markdown(f"**Artwork {_text(evaluation, 'artwork_id')}** · {decision}")
            _metric_row(
                [
                    ("Readability", f"{float(evaluation.get('readability') or 0):.1f}"),
                    ("Composition", f"{float(evaluation.get('composition') or 0):.1f}"),
                    ("Quality", f"{float(evaluation.get('quality') or 0):.1f}"),
                    ("Alignment", f"{float(evaluation.get('alignment') or 0):.1f}"),
                ]
            )
            checks = evaluation.get("checks", {})
            if isinstance(checks, dict):
                st.write(" · ".join(("✓ " if value else "✗ ") + str(key).replace("_", " ") for key, value in checks.items()))
            issues = evaluation.get("issues", [])
            if issues:
                st.warning(" · ".join(str(issue) for issue in issues))


def _render_artwork_revision(payload: dict[str, Any]) -> None:
    """Show Grok's edit decisions and prompts without implying a second visual verification."""

    revisions = _records(payload, "revisions")
    revised = sum(bool(item.get("revised")) for item in revisions)
    _metric_row([("Artwork candidates", str(len(revisions))), ("Grok edits", str(revised))])
    for revision in revisions:
        with st.container(border=True):
            status = _text(revision, "status", default="unknown").replace("_", " ").title()
            st.markdown(f"**Artwork {_text(revision, 'artwork_id')}** · {status}")
            edit_prompt = revision.get("edit_prompt")
            if edit_prompt:
                with st.expander("Grok edit prompt"):
                    st.code(str(edit_prompt), language="text")
            else:
                st.caption("No edit requested; the Luna-approved artwork passed through unchanged.")


def _render_generic(payload: dict[str, Any]) -> None:
    """Provide a readable fallback for future stages without exposing raw JSON."""

    collections = [(key.replace("_", " ").title(), len(value)) for key, value in payload.items() if isinstance(value, list)]
    if collections:
        _metric_row([(label, str(count)) for label, count in collections[:4]])
    else:
        st.caption("This stage has persisted output, but no overview renderer is defined yet.")


RENDERERS: dict[int, PayloadRenderer] = {
    1: _render_seed_discovery,
    2: _render_identity_expansion,
    3: _render_intersections,
    4: _render_coherence,
    5: _render_filter,
    6: _render_research,
    7: _render_experience_mining,
    8: _render_opportunity_scoring,
    9: _render_concepts,
    10: _render_critique,
    11: _render_similarity,
    12: _render_selection,
    13: _render_briefs,
    14: _render_prompts,
    15: _render_artwork_generation,
    16: _render_artwork_critique,
    17: _render_artwork_revision,
    18: _render_artwork_gallery,
}


def render_stage_overview(stage: StageFixture) -> None:
    """Render a stage's useful overview while preserving honest empty/pending states."""

    if stage.progress and stage.status == StageStatus.RUNNING:
        st.progress(stage.progress / 100, text=f"Stage progress · {stage.progress}%")
    if stage.metrics:
        # Attempt/version remain available in the right-hand audit panel; the pipeline card should
        # lead with stage decisions and provider consumption rather than storage bookkeeping.
        card_metrics = [
            (label, value)
            for label, value in stage.metrics.items()
            if label not in {"Attempt", "State version"}
        ]
        _metric_row(card_metrics)
    if not stage.output_payload:
        if stage.status == StageStatus.PENDING:
            st.info(f"⏳ Stage {stage.number:02d} ({stage.name}) is pending execution.")
        else:
            st.info(stage.output_summary)
            st.caption("Structured stage output will appear here after execution.")
        return
    # Compact pipelines reuse the artwork implementations under different stage numbers. Resolve
    # those names first so a compact artwork record is not rendered as an unrelated baseline stage.
    if "to Merchandise Text" in stage.name or "Identity Mapping" in stage.name:
        _render_social_behavior_text(stage.output_payload, stage.input_payload)
        return
    elif "Artwork Results" in stage.name or "Artwork Gallery" in stage.name:
        renderer = _render_artwork_gallery
    elif "Artwork Generation" in stage.name:
        renderer = _render_artwork_generation
    elif "Artwork Critique" in stage.name:
        renderer = _render_artwork_critique
    elif "Artwork Revision" in stage.name:
        # Historical compact Stage 9 and baseline Stage 17 records were already galleries before
        # the revision stage existed; use their payload shape to preserve old run readability.
        renderer = (
            _render_artwork_revision
            if "revisions" in stage.output_payload
            else _render_artwork_gallery
        )
    elif "AI Merchandise Development" in stage.name:
        renderer = _render_research
    elif stage.number in {9, 10} and "artworks" in stage.output_payload:
        # Legacy compact runs may still contain an older stage label, but their payload is already
        # compatible with the display-only gallery.
        renderer = _render_artwork_gallery
    else:
        renderer = RENDERERS.get(stage.number, _render_generic)
    renderer(stage.output_payload)
