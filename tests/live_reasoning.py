"""Doubles for a live social stage that now drafts, then always calls the critic."""

from types import SimpleNamespace
from unittest.mock import Mock

from merchandise_discovery.domain.humor import (
    HumorCritiqueBatch,
    HumorCritiqueItem,
    NichePairBatch,
    NichePairCandidate,
)
from merchandise_discovery.domain.models.usage import UsageMetrics


def scripted_social_provider(output, usage: UsageMetrics | None = None) -> Mock:
    """Return the drafted lines for the writer and a passing score for every critic index."""

    measured = usage or UsageMetrics(provider="openai", model="gpt-5", request_count=1)
    provider = Mock()

    def respond(**kwargs):
        model = kwargs["response_model"]
        name = getattr(model, "__name__", "")
        if name == "HumorCritiqueBatch":
            return SimpleNamespace(
                output=HumorCritiqueBatch(
                    reviews=[
                        HumorCritiqueItem(
                            index=index,
                            humor_landed=8,
                            novelty=8,
                            tone_match=8,
                            giftability=6,
                            reddit_upvote_score=8,
                            sticker_buy_score=8,
                        )
                        for index in range(30)
                    ]
                ),
                usage=UsageMetrics(provider=measured.provider, model=measured.model, request_count=1),
            )
        if name == "NichePairBatch":
            return SimpleNamespace(
                output=NichePairBatch(
                    pairs=[
                        NichePairCandidate(
                            niche_a="nurses",
                            niche_b="true crime",
                            shared_life_score=9,
                            recognizability_score=9,
                            reason="Night shifts and the same podcast.",
                        ),
                        NichePairCandidate(
                            niche_a="dads",
                            niche_b="grilling",
                            shared_life_score=8,
                            recognizability_score=8,
                            reason="Weekend ritual.",
                        ),
                        NichePairCandidate(
                            niche_a="accountants",
                            niche_b="scuba",
                            shared_life_score=3,
                            recognizability_score=4,
                            reason="No shared life.",
                        ),
                    ]
                ),
                usage=UsageMetrics(provider=measured.provider, model=measured.model, request_count=1),
            )
        return SimpleNamespace(output=output, usage=measured)

    provider.complete_structured.side_effect = respond
    return provider


def first_writer_call(provider: Mock):
    """The first structured call is the merchandise writer. Later calls are the critic or a rewrite."""

    for call in provider.complete_structured.call_args_list:
        name = getattr(call.kwargs["response_model"], "__name__", "")
        if name not in {"HumorCritiqueBatch", "NichePairBatch"}:
            return call
    raise AssertionError("the writer was never called")
