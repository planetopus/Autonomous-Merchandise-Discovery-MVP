"""Tests for the OpenAI adapter's model-specific request boundary.

The provider owns SDK compatibility so domain stages remain unchanged when the configured
reasoning model changes. These tests verify both supported and unsupported request shapes without
making a paid network call.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from merchandise_discovery.infrastructure.providers.reasoning_provider import (
    OpenAIReasoningProvider,
    ReasoningProviderError,
)


class ExampleOutput(BaseModel):
    value: str


def _provider(model: str, *, reasoning_effort: str = "medium") -> OpenAIReasoningProvider:
    """Construct an adapter with a mocked SDK client and no network access."""

    with patch("merchandise_discovery.infrastructure.providers.reasoning_provider.OpenAI") as client:
        provider = OpenAIReasoningProvider(
            api_key="test-key",
            model=model,
            reasoning_effort=reasoning_effort,
        )
    provider._client = client.return_value
    provider._client.responses.parse.return_value = SimpleNamespace(
        output_parsed=ExampleOutput(value="ok"),
        usage=SimpleNamespace(input_tokens=2, output_tokens=3, total_tokens=5),
    )
    return provider


def test_reasoning_models_omit_temperature() -> None:
    """GPT-5.6 and GPT-6 Luna receive reasoning effort, not temperature."""

    provider = _provider("gpt-6-luna")

    provider.complete_structured(
        system_prompt="system",
        user_prompt="user",
        response_model=ExampleOutput,
        temperature=0.0,
    )

    kwargs = provider._client.responses.parse.call_args.kwargs
    assert "temperature" not in kwargs
    assert kwargs["reasoning"] == {"effort": "medium"}
    assert kwargs["model"] == "gpt-6-luna"


def test_reasoning_effort_is_configurable_for_gpt5_models() -> None:
    """Existing GPT-5 reasoning requests can explicitly use the configured effort level."""

    provider = _provider("gpt-5.6-luna", reasoning_effort="low")

    provider.complete_structured(
        system_prompt="system",
        user_prompt="user",
        response_model=ExampleOutput,
        temperature=0.0,
    )

    kwargs = provider._client.responses.parse.call_args.kwargs
    assert kwargs["reasoning"] == {"effort": "low"}
    assert "temperature" not in kwargs


def test_vision_model_override_does_not_send_reasoning_controls() -> None:
    """The text check calls gpt-4o-mini on a gpt-5 provider. That call must not send reasoning."""

    provider = _provider("gpt-5")

    result = provider.complete_structured(
        system_prompt="system",
        user_prompt="read the sticker",
        response_model=ExampleOutput,
        temperature=0.0,
        model="gpt-4o-mini",
    )

    kwargs = provider._client.responses.parse.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["temperature"] == 0.0
    assert "reasoning" not in kwargs
    assert result.usage.model == "gpt-4o-mini"


def test_chat_models_keep_temperature() -> None:
    """Existing GPT-4o-mini runs retain their deterministic temperature setting."""

    provider = _provider("gpt-4o-mini")

    provider.complete_structured(
        system_prompt="system",
        user_prompt="user",
        response_model=ExampleOutput,
        temperature=0.0,
    )

    assert provider._client.responses.parse.call_args.kwargs["temperature"] == 0.0
    assert "reasoning" not in provider._client.responses.parse.call_args.kwargs


def test_structured_web_search_cost_includes_tool_call_fee() -> None:
    """Social search calls include the configured web-search fee in their cost estimate."""

    provider = _provider("gpt-6-luna")
    result = provider.complete_structured(
        system_prompt="system",
        user_prompt="find behavior",
        response_model=ExampleOutput,
        web_search_domains=("reddit.com",),
    )

    kwargs = provider._client.responses.parse.call_args.kwargs
    assert kwargs["tool_choice"] == "required"
    assert result.usage.estimated_cost_usd == 0.0100021
    assert "web-search call" in (result.usage.pricing_note or "")


def test_provider_builds_multimodal_structured_request() -> None:
    """Artwork critique sends text context and the image through the same Responses boundary."""

    provider = _provider("gpt-5.6-luna")
    provider.complete_structured(
        system_prompt="system",
        user_prompt="review this artwork",
        response_model=ExampleOutput,
        image_url="https://example.com/artwork.png",
        image_detail="high",
    )

    content = provider._client.responses.parse.call_args.kwargs["input"][1]["content"]
    assert content[0] == {"type": "input_text", "text": "review this artwork"}
    assert content[1] == {
        "type": "input_image",
        "image_url": "https://example.com/artwork.png",
        "detail": "high",
    }


def test_provider_requires_domain_restricted_web_search_when_requested() -> None:
    """The social pipeline cannot silently answer without searching its requested platforms."""

    provider = _provider("gpt-5")
    provider.complete_structured(
        system_prompt="system",
        user_prompt="find behavior",
        response_model=ExampleOutput,
        web_search_domains=("reddit.com", "x.com"),
    )

    kwargs = provider._client.responses.parse.call_args.kwargs
    assert kwargs["tool_choice"] == "required"
    assert kwargs["tools"] == [
        {
            "type": "web_search",
            "filters": {"allowed_domains": ["reddit.com", "x.com"]},
        }
    ]


def test_search_web_uses_the_openai_web_search_tool() -> None:
    """Listing checks use the same web-search tool, without a domain filter."""

    provider = _provider("gpt-5")
    annotation = SimpleNamespace(
        url="https://www.teepublic.com/t-shirt/calm-during-your-worst-day",
        title="Calm during your worst day sticker",
    )
    provider._client.responses.create.return_value = SimpleNamespace(
        output=[SimpleNamespace(content=[SimpleNamespace(annotations=[annotation])])],
        usage=SimpleNamespace(input_tokens=2, output_tokens=3, total_tokens=5),
    )

    citations, usage = provider.search_web('"Calm during your worst day" sticker OR shirt OR decal')

    kwargs = provider._client.responses.create.call_args.kwargs
    assert kwargs["tools"] == [{"type": "web_search"}]
    assert kwargs["tool_choice"] == "required"
    assert kwargs["reasoning"] == {"effort": "low"}
    assert citations == [
        {
            "url": "https://www.teepublic.com/t-shirt/calm-during-your-worst-day",
            "title": "Calm during your worst day sticker",
        }
    ]
    assert usage.request_count == 1
    assert "web-search call" in (usage.pricing_note or "")


def test_models_without_web_search_filters_fail_before_the_request() -> None:
    """gpt-4o-mini rejects web_search filters, so the adapter stops with a model hint."""

    provider = _provider("gpt-4o-mini")

    with pytest.raises(ReasoningProviderError, match="does not support web_search filters"):
        provider.complete_structured(
            system_prompt="system",
            user_prompt="find behavior",
            response_model=ExampleOutput,
            web_search_domains=("reddit.com",),
        )

    provider._client.responses.parse.assert_not_called()


def test_direct_provider_uses_environment_timeout(monkeypatch) -> None:
    """Direct adapter construction follows the same timeout contract as application runtimes."""

    monkeypatch.setenv("OPENAI_REASONING_TIMEOUT_SECONDS", "123")

    with patch("merchandise_discovery.infrastructure.providers.reasoning_provider.OpenAI") as client:
        OpenAIReasoningProvider(api_key="test-key")

    client.assert_called_once_with(api_key="test-key", timeout=123.0)


def test_provider_error_includes_safe_provider_detail() -> None:
    """Stage logs should identify the upstream rejection instead of hiding it completely."""

    provider = _provider("gpt-5.6-luna")
    provider._client.responses.parse.side_effect = ValueError("temperature is unsupported")

    with pytest.raises(ReasoningProviderError, match="temperature is unsupported"):
        provider.complete_structured(
            system_prompt="system",
            user_prompt="user",
            response_model=ExampleOutput,
        )
