"""Image-generation provider boundary, fixture adapter, and xAI implementation.

Stage 15 depends on this contract rather than an SDK. The default fixture provider creates
inspectable metadata only; the application storage adapter persists live provider binaries without
changing the stage or worker protocol.
"""

import base64
import re
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from openai import OpenAI, OpenAIError

from merchandise_discovery.domain.models.usage import UsageMetrics


@dataclass(frozen=True)
class ImageGenerationRequest:
    """Prompt and variant identity supplied to an image provider."""

    concept_id: str
    brief_id: str
    prompt: str
    variant_number: int


@dataclass(frozen=True)
class ImageEditRequest:
    """Original artwork and the targeted correction supplied to an image-edit provider."""

    artwork_id: str
    source_url: str
    prompt: str


@dataclass(frozen=True)
class GeneratedImage:
    """Provider-neutral image metadata returned before it becomes an Artwork artifact."""

    source_url: str
    storage_key: str
    width: int
    height: int
    mime_type: str
    file_size_bytes: int
    usage: UsageMetrics = field(default_factory=UsageMetrics)
    content: bytes | None = None


OPENAI_IMAGE_MODEL = "gpt-image-1"
OPENAI_IMAGE_PRICE = 0.04


def image_backend_name(openai_key: str | None, xai_key: str | None, *, live: bool) -> str:
    """Prefer OpenAI gpt-image-1, then xAI, then the fixture provider."""

    if live and (openai_key or "").strip():
        return f"openai {OPENAI_IMAGE_MODEL}"
    if live and (xai_key or "").strip():
        return "xAI image generation"
    return "fixture"


def estimate_image_cost(backend: str, count: int = 5) -> float:
    """Rough dollars for one run's sticker images. Text tokens are separate."""

    if count <= 0:
        return 0.0
    name = backend.casefold()
    if "gpt-image" in name or name.startswith("openai"):
        return round(OPENAI_IMAGE_PRICE * count, 2)
    if "xai" in name:
        return round(0.02 * count, 2)
    return 0.0


class ImageProvider(Protocol):
    """Contract implemented by fixture and xAI image providers."""

    def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        """Generate one candidate and return metadata for durable storage."""

    def edit(self, request: ImageEditRequest) -> GeneratedImage:
        """Edit one existing candidate and return metadata for durable storage."""


class FixtureImageProvider:
    """Return deterministic image-shaped metadata without network calls or API credits."""

    def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        """Create a stable fixture reference for one concept/variant pair."""

        slug = re.sub(r"[^a-z0-9]+", "-", request.concept_id.lower()).strip("-")
        storage_key = f"fixture-artwork/{slug}/variant-{request.variant_number}.png"
        return GeneratedImage(
            source_url=f"https://fixture.local/artwork/{slug}/{request.variant_number}.png",
            storage_key=storage_key,
            width=1024,
            height=1024,
            mime_type="image/png",
            file_size_bytes=128_000,
        )

    def edit(self, request: ImageEditRequest) -> GeneratedImage:
        """Represent an edit deterministically without downloading or calling an API."""

        return GeneratedImage(
            source_url=f"{request.source_url}?fixture_edit=1",
            storage_key=f"fixture-artwork/{request.artwork_id}/edited.png",
            width=1024,
            height=1024,
            mime_type="image/png",
            file_size_bytes=128_000,
        )


class OpenAIImageProvider:
    """Generate one sticker with OpenAI gpt-image-1 and return the PNG bytes."""

    def __init__(
        self,
        api_key: str,
        model: str = OPENAI_IMAGE_MODEL,
        price_per_image: float = OPENAI_IMAGE_PRICE,
    ):
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._price_per_image = price_per_image

    def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        """Submit one prompt. gpt-image-1 returns base64, not a hosted URL."""

        try:
            response = self._client.images.generate(
                model=self._model,
                prompt=request.prompt,
                size="1024x1024",
                quality="medium",
            )
        except (OpenAIError, TypeError, ValueError) as error:
            raise RuntimeError("OpenAI image generation request failed.") from error
        if not response.data:
            raise RuntimeError("OpenAI image generation returned no image.")
        record = response.data[0]
        raw = getattr(record, "b64_json", None)
        content = base64.b64decode(raw) if raw else None
        source_url = getattr(record, "url", None) or f"openai://{self._model}/{request.concept_id}"
        if content is None and not getattr(record, "url", None):
            raise RuntimeError("OpenAI image generation returned no image bytes.")
        slug = re.sub(r"[^a-z0-9]+", "-", request.concept_id.lower()).strip("-")
        return GeneratedImage(
            source_url=source_url,
            storage_key=f"openai-artwork/{slug}/variant-{request.variant_number}.png",
            width=1024,
            height=1024,
            mime_type="image/png",
            file_size_bytes=len(content) if content else 128_000,
            content=content,
            usage=UsageMetrics(
                provider="openai",
                model=self._model,
                request_count=1,
                image_count=1,
                estimated_cost_usd=self._price_per_image,
                cost_is_estimate=True,
                pricing_note="Estimated at $0.04 per gpt-image-1 medium 1024 image.",
            ),
        )

    def edit(self, request: ImageEditRequest) -> GeneratedImage:
        """Editing stays on the xAI path. This provider only generates finished stickers."""

        raise RuntimeError("OpenAI sticker generation does not edit an existing image.")


class XAIImageProvider:
    """Generate merchandise artwork through xAI's OpenAI-compatible image endpoint."""

    def __init__(
        self,
        api_key: str,
        model: str = "grok-imagine-image",
        price_per_image: float = 0.02,
        edit_price_per_image: float = 0.022,
    ):
        self._client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        self._api_key = api_key
        self._model = model
        self._price_per_image = price_per_image
        self._edit_price_per_image = edit_price_per_image

    def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        """Submit one prompt and return the provider URL plus an estimated fixed image cost."""

        try:
            response = self._client.images.generate(model=self._model, prompt=request.prompt)
        except (OpenAIError, TypeError, ValueError) as error:
            raise RuntimeError("xAI image generation request failed.") from error
        if not response.data or not getattr(response.data[0], "url", None):
            raise RuntimeError("xAI image generation returned no image URL.")
        source_url = response.data[0].url
        slug = re.sub(r"[^a-z0-9]+", "-", request.concept_id.lower()).strip("-")
        return GeneratedImage(
            source_url=source_url,
            storage_key=f"xai-artwork/{slug}/variant-{request.variant_number}.png",
            width=1024,
            height=1024,
            mime_type="image/png",
            # xAI returns a hosted URL; Stage 15's storage adapter downloads it and replaces this
            # estimate with the measured binary size before MongoDB persistence.
            file_size_bytes=128_000,
            usage=UsageMetrics(
                provider="xai",
                model=self._model,
                request_count=1,
                image_count=1,
                estimated_cost_usd=self._price_per_image,
                cost_is_estimate=True,
                pricing_note="Estimated from configured xAI per-image pricing.",
            ),
        )

    def edit(self, request: ImageEditRequest) -> GeneratedImage:
        """Call xAI's JSON image-edit endpoint and convert its result to the image contract.

        xAI's edit endpoint intentionally uses JSON rather than the OpenAI SDK's multipart
        ``images.edit`` helper. Keeping this request here prevents the stage from depending on
        that provider-specific transport detail.
        """

        if not request.source_url or request.source_url.startswith("https://fixture.local/"):
            raise RuntimeError("xAI artwork editing requires a public source image URL.")
        payload = {
            "model": self._model,
            "prompt": request.prompt,
            "image": {"url": request.source_url, "type": "image_url"},
        }
        try:
            with httpx.Client(timeout=420.0) as client:
                response = client.post(
                    "https://api.x.ai/v1/images/edits",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise RuntimeError("xAI artwork edit request failed.") from error

        records = result.get("data") if isinstance(result, dict) else None
        source_url = records[0].get("url") if records and isinstance(records[0], dict) else None
        if not source_url:
            raise RuntimeError("xAI artwork edit returned no image URL.")

        usage = result.get("usage", {}) if isinstance(result, dict) else {}
        ticks = usage.get("cost_in_usd_ticks") if isinstance(usage, dict) else None
        measured_cost = (
            float(ticks) / 10_000_000_000
            if isinstance(ticks, (int, float))
            else self._edit_price_per_image
        )
        slug = re.sub(r"[^a-z0-9]+", "-", request.artwork_id.lower()).strip("-")
        return GeneratedImage(
            source_url=source_url,
            storage_key=f"xai-artwork-edits/{slug}.jpeg",
            width=1024,
            height=1024,
            mime_type=(records[0].get("mime_type") or "image/jpeg"),
            file_size_bytes=128_000,
            usage=UsageMetrics(
                provider="xai",
                model=self._model,
                request_count=1,
                image_count=1,
                estimated_cost_usd=round(measured_cost, 8),
                cost_is_estimate=True,
                pricing_note=(
                    "Measured from xAI cost_in_usd_ticks."
                    if isinstance(ticks, (int, float))
                    else "Estimated from configured xAI per-edit image pricing."
                ),
            ),
        )
