"""Image failures keep the provider status, then try the next image backend."""

from types import SimpleNamespace

from merchandise_discovery.infrastructure.providers.image_provider import (
    FallbackImageProvider,
    GeneratedImage,
    ImageGenerationRequest,
    gpt_image_generate_kwargs,
    public_image_error,
)


class _Boom:
    def generate(self, request):
        raise RuntimeError(
            "OpenAI gpt-image-1 image generation failed HTTP 403: "
            "organization must be verified to use gpt-image-1 sk-secretkey12345678"
        )

    def edit(self, request):
        raise RuntimeError("no edit")


class _Ok:
    def __init__(self):
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        return GeneratedImage(
            source_url="https://example.test/sticker.png",
            storage_key="xai/sticker.png",
            width=1024,
            height=1024,
            mime_type="image/png",
            file_size_bytes=10,
        )

    def edit(self, request):
        return self.generate(request)


def test_gpt_image_params_skip_response_format() -> None:
    """gpt-image-1 rejects response_format and always returns base64."""

    params = gpt_image_generate_kwargs("a die-cut sticker")
    assert params["model"] == "gpt-image-1"
    assert params["size"] == "1024x1024"
    assert params["quality"] == "medium"
    assert params["output_format"] == "png"
    assert "response_format" not in params


def test_public_error_keeps_status_and_hides_the_key() -> None:
    """The run page can show the HTTP status without a secret."""

    error = SimpleNamespace(
        status_code=403,
        message="Verify the org before using gpt-image-1 sk-abcDEFghij123456",
    )
    text = public_image_error("OpenAI gpt-image-1", error)
    assert "HTTP 403" in text
    assert "Verify the org" in text
    assert "sk-" not in text


def test_openai_failure_uses_the_next_provider_once() -> None:
    """A rejected gpt-image-1 call falls through and is not tried again."""

    backup = _Ok()
    provider = FallbackImageProvider([("OpenAI gpt-image-1", _Boom()), ("xAI grok-imagine-image", backup)])
    request = ImageGenerationRequest("c1", "b1", "prompt", 1)

    labels: dict[str, str] = {"image": "OpenAI gpt-image-1"}
    provider.label_store = labels
    first = provider.generate(request)
    note = provider.fallback_note
    second = provider.generate(request)

    assert first.source_url.endswith("sticker.png")
    assert backup.calls == 2
    assert "HTTP 403" in note
    assert "sk-" not in note
    assert note.count("Used xAI") == 1
    assert provider.fallback_note == note
    assert labels["image"] == "xAI grok-imagine-image"
    assert second.source_url == first.source_url
