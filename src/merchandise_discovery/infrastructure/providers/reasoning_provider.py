"""Reasoning-model adapters for provider-backed structured generation and critique.

Stages depend on this boundary rather than importing the OpenAI SDK. Live provider use is injected
by the application runtime, while fixture or deterministic paths remain available when live mode is
disabled or no live provider is configured. Provider failures are propagated to stage handling.
"""

import os
from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI, OpenAIError
from pydantic import BaseModel

from merchandise_discovery.domain.models.usage import UsageMetrics
from merchandise_discovery.infrastructure.providers.openai_model_compatibility import (
    is_reasoning_model,
    supports_web_search_filters,
)


class ReasoningProviderError(RuntimeError):
    """Raised when a structured reasoning response cannot be produced or parsed."""


def _usage_count(usage: object, *names: str) -> int:
    """Read a token count from an SDK object or a dict, treating a missing usage block as zero."""

    if usage is None:
        return 0
    for name in names:
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        if value:
            return int(value)
    return 0


@dataclass(frozen=True)
class StructuredResponse:
    """Typed model output plus the usage returned by the provider."""

    output: BaseModel
    usage: UsageMetrics


class ReasoningProvider(Protocol):
    """Provider contract for typed reasoning requests."""

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        temperature: float = 0.0,
        image_url: str | None = None,
        image_detail: str = "high",
        web_search_domains: tuple[str, ...] | None = None,
        reasoning_effort: str | None = None,
    ) -> StructuredResponse:
        """Return a validated Pydantic response and measured usage for one request.

        ``image_url`` is optional so the same boundary serves text-only stages and vision-aware
        artwork critique. The adapter owns the provider-specific multimodal request shape.
        """


class OpenAIReasoningProvider:
    """Use OpenAI structured outputs behind the application provider boundary."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5",
        *,
        input_price_per_million: float = 0.15,
        output_price_per_million: float = 0.60,
        reasoning_effort: str = "medium",
        web_search_price_per_call: float = 0.01,
        timeout_seconds: float | None = None,
    ):
        # Composition roots normally pass the validated Settings value. The environment fallback
        # keeps direct adapter construction consistent for scripts and isolated integrations.
        if timeout_seconds is None:
            try:
                timeout_seconds = max(
                    1.0, float(os.getenv("OPENAI_REASONING_TIMEOUT_SECONDS", "420"))
                )
            except ValueError:
                timeout_seconds = 420.0
        # A bounded timeout prevents a failed live provider from holding a background stage open
        # indefinitely. The stage runner records the resulting provider error as a failure.
        self._client = OpenAI(api_key=api_key, timeout=timeout_seconds)
        self._model = model
        self._input_price = input_price_per_million
        self._output_price = output_price_per_million
        self._reasoning_effort = reasoning_effort
        self._web_search_price_per_call = web_search_price_per_call

    def _supports_temperature(self) -> bool:
        """Return whether this model family accepts the legacy sampling parameter.

        The stage contract keeps ``temperature`` so callers do not need to know provider
        quirks. Newer reasoning families (including GPT-5.x and the o-series) control
        generation through reasoning settings and reject ``temperature`` in reasoning modes,
        so the adapter must omit it at the provider boundary.
        """

        return not is_reasoning_model(self._model)

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        temperature: float = 0.0,
        image_url: str | None = None,
        image_urls: list[str] | None = None,
        image_detail: str = "high",
        web_search_domains: tuple[str, ...] | None = None,
        reasoning_effort: str | None = None,
        model: str | None = None,
    ) -> StructuredResponse:
        """Submit one typed request and convert provider usage into the application contract."""

        # Keep model-specific request shaping here. Stages can request deterministic behavior
        # without coupling themselves to the parameter rules of whichever reasoning model is
        # configured for the run.
        pictures = [url for url in (image_urls or []) if url]
        if image_url:
            pictures.insert(0, image_url)
        user_content: str | list[dict[str, object]] = user_prompt
        if pictures:
            if image_detail not in {"low", "high", "auto", "original"}:
                raise ValueError(f"Unsupported OpenAI image detail level: {image_detail}")
            user_content = [{"type": "input_text", "text": user_prompt}]
            user_content.extend(
                {
                    "type": "input_image",
                    "image_url": url,
                    "detail": image_detail,
                }
                for url in pictures
            )

        chosen_model = (model or self._model).strip() or self._model
        request_kwargs: dict[str, object] = {
            "model": chosen_model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "text_format": response_model,
        }
        if web_search_domains:
            if not supports_web_search_filters(chosen_model):
                raise ReasoningProviderError(
                    f"Model {chosen_model!r} does not support web_search filters "
                    "(the API reports Parameter 'filters' not supported). "
                    "Set OPENAI_REASONING_MODEL to gpt-5 or a newer reasoning model."
                )
            request_kwargs["tools"] = [
                {
                    "type": "web_search",
                    "filters": {"allowed_domains": list(web_search_domains)},
                }
            ]
            # This pipeline must inspect social sources; a text-only answer should not look like
            # successful source extraction when the provider did not search the requested domains.
            request_kwargs["tool_choice"] = "required"
        # The sticker text check calls a vision model on a provider whose default
        # model is a reasoning model. Controls follow the model on this request.
        if is_reasoning_model(chosen_model):
            request_kwargs["reasoning"] = {"effort": reasoning_effort or self._reasoning_effort}
        else:
            request_kwargs["temperature"] = temperature

        try:
            response = self._client.responses.parse(**request_kwargs)
        except (OpenAIError, TypeError, ValueError) as error:
            # Preserve the provider's actionable reason while keeping the application-facing
            # exception stable enough for stage logging and UI rendering.
            detail = str(error).strip() or type(error).__name__
            if "filters" in detail.casefold() and "not supported" in detail.casefold():
                detail = (
                    f"Model {chosen_model!r} does not support web_search filters. "
                    "Set OPENAI_REASONING_MODEL to gpt-5 or a newer reasoning model. "
                    f"Provider said: {detail}"
                )
            raise ReasoningProviderError(
                f"Structured reasoning request failed: {detail[:500]}"
            ) from error
        if response.output_parsed is None:
            raise ReasoningProviderError("Structured reasoning response was empty or invalid.")
        search_cost = self._web_search_price_per_call if web_search_domains else 0.0
        return StructuredResponse(
            output=response.output_parsed,
            usage=self._usage_metrics(response.usage, search_cost, chosen_model),
        )

    def search_web(self, query: str) -> tuple[list[dict[str, str]], UsageMetrics]:
        """Run one OpenAI web search and return citation URLs plus the measured cost.

        This is the same Responses web-search tool the research and social stages use,
        without a domain filter, so a phrase can be checked on any store.
        """

        request_kwargs: dict[str, object] = {
            "model": self._model,
            "tools": [{"type": "web_search"}],
            "tool_choice": "required",
            "input": query,
        }
        if is_reasoning_model(self._model):
            request_kwargs["reasoning"] = {"effort": "low"}
        try:
            response = self._client.responses.create(**request_kwargs)
        except (OpenAIError, TypeError, ValueError) as error:
            detail = str(error).strip() or type(error).__name__
            raise ReasoningProviderError(f"Web search failed: {detail[:500]}") from error
        citations: list[dict[str, str]] = []
        seen: set[str] = set()
        for annotation in _iter_annotations(response):
            url = _annotation_value(annotation, "url")
            if not url or url in seen:
                continue
            seen.add(url)
            title = _annotation_value(annotation, "title") or url
            citations.append({"url": url, "title": title})
        return citations, self._usage_metrics(
            getattr(response, "usage", None),
            self._web_search_price_per_call,
        )

    def search_web_cheap(self, query: str) -> tuple[list[dict[str, str]], UsageMetrics]:
        """Phrase check on a non-reasoning model. The sale screen uses this, not gpt-5."""

        model = os.getenv("MVP_SALE_SEARCH_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        request_kwargs: dict[str, object] = {
            "model": model,
            "tools": [{"type": "web_search"}],
            "tool_choice": "required",
            "input": query,
        }
        try:
            response = self._client.responses.create(**request_kwargs)
        except (OpenAIError, TypeError, ValueError) as error:
            detail = str(error).strip() or type(error).__name__
            raise ReasoningProviderError(f"Web search failed: {detail[:500]}") from error
        citations: list[dict[str, str]] = []
        seen: set[str] = set()
        for annotation in _iter_annotations(response):
            url = _annotation_value(annotation, "url")
            if not url or url in seen:
                continue
            seen.add(url)
            title = _annotation_value(annotation, "title") or url
            citations.append({"url": url, "title": title})
        return citations, self._usage_metrics(
            getattr(response, "usage", None),
            self._web_search_price_per_call,
            model,
        )

    def _usage_metrics(
        self,
        provider_usage: object,
        search_cost: float,
        model: str | None = None,
    ) -> UsageMetrics:
        """Convert one Responses usage block into the application cost contract."""

        input_tokens = _usage_count(provider_usage, "input_tokens", "prompt_tokens")
        output_tokens = _usage_count(provider_usage, "output_tokens", "completion_tokens")
        return UsageMetrics(
            provider="openai",
            model=model or self._model,
            request_count=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=_usage_count(provider_usage, "total_tokens") or input_tokens + output_tokens,
            estimated_cost_usd=round(
                input_tokens * self._input_price / 1_000_000
                + output_tokens * self._output_price / 1_000_000
                + search_cost,
                8,
            ),
            cost_is_estimate=True,
            pricing_note=(
                "Estimated from configured OpenAI per-million-token rates"
                + (
                    f" plus ${search_cost:.2f} for the web-search call."
                    if search_cost
                    else "."
                )
            ),
        )


def _iter_annotations(response: object):
    """Yield citation annotations from a Responses web-search result."""

    for item in getattr(response, "output", None) or []:
        content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
        for block in content or []:
            annotations = (
                block.get("annotations")
                if isinstance(block, dict)
                else getattr(block, "annotations", None)
            )
            yield from annotations or []


def _annotation_value(annotation: object, name: str) -> str:
    if isinstance(annotation, dict):
        return str(annotation.get(name) or "")
    return str(getattr(annotation, name, "") or "")
