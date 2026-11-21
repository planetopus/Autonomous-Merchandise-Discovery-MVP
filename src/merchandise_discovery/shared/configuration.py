"""Application configuration loading and environment-variable validation.

Configuration is read at process boundaries so importing domain modules never requires credentials.
This keeps tests deterministic and prevents secrets from leaking into UI code.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from merchandise_discovery.shared.errors import ConfigurationError

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


@dataclass(frozen=True)
class Settings:
    """Runtime settings shared by the Streamlit process and workflow worker."""

    mongodb_uri: str | None
    mongodb_database: str
    openai_api_key: str | None
    xai_api_key: str | None
    xai_image_model: str
    artwork_storage_dir: str = ".artifacts"
    max_stage_attempts: int = 3
    openai_reasoning_model: str = "gpt-5"
    openai_reasoning_effort: str = "medium"
    openai_reasoning_timeout_seconds: float = 420.0
    openai_image_detail: str = "high"
    openai_input_price_per_million: float = 0.15
    openai_output_price_per_million: float = 0.60
    openai_web_search_price_per_call: float = 0.01
    xai_image_price: float = 0.02
    xai_image_edit_price: float = 0.022
    etsy_api_key: str | None = None
    ebay_app_token: str | None = None
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str | None = None
    humor_reference_csv_url: str | None = None
    provider_mode: str = "fixture"
    # The current MVP intentionally evaluates only Stage 1 until the client approves expanding
    # the funnel. This is a demo boundary, not a claim that later stages are complete.
    stop_after_stage: int = 1
    trending_share: float = 0.6


def load_settings() -> Settings:
    """Load environment variables without requiring optional provider credentials at import time."""

    if ENV_FILE.is_file():
        load_dotenv(dotenv_path=ENV_FILE, override=False)
    else:
        load_dotenv(override=False)
    reasoning_model = os.getenv("OPENAI_REASONING_MODEL", "gpt-5").strip() or "gpt-5"
    default_input_price, default_output_price = _default_openai_token_prices(reasoning_model)
    return Settings(
        mongodb_uri=os.getenv("MONGODB_URI"),
        mongodb_database=os.getenv("MONGODB_DATABASE", "merchandise_discovery"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        xai_api_key=os.getenv("XAI_API_KEY"),
        xai_image_model=os.getenv("XAI_IMAGE_MODEL", "grok-imagine-image"),
        artwork_storage_dir=os.getenv("ARTWORK_STORAGE_DIR", ".artifacts"),
        max_stage_attempts=max(1, int(os.getenv("MVP_MAX_STAGE_ATTEMPTS", "3"))),
        openai_reasoning_model=reasoning_model,
        openai_reasoning_effort=(
            os.getenv("OPENAI_REASONING_EFFORT", "medium").strip().lower() or "medium"
        ),
        openai_reasoning_timeout_seconds=max(
            1.0, float(os.getenv("OPENAI_REASONING_TIMEOUT_SECONDS", "420"))
        ),
        openai_image_detail=os.getenv("OPENAI_IMAGE_DETAIL", "high").strip().lower(),
        openai_input_price_per_million=float(
            os.getenv("OPENAI_INPUT_PRICE_PER_MILLION", str(default_input_price))
        ),
        openai_output_price_per_million=float(
            os.getenv("OPENAI_OUTPUT_PRICE_PER_MILLION", str(default_output_price))
        ),
        openai_web_search_price_per_call=float(
            os.getenv("OPENAI_WEB_SEARCH_PRICE_PER_CALL", "0.01")
        ),
        xai_image_price=float(os.getenv("XAI_IMAGE_PRICE", "0.02")),
        xai_image_edit_price=float(os.getenv("XAI_IMAGE_EDIT_PRICE", "0.022")),
        etsy_api_key=_optional_secret("ETSY_API_KEY"),
        ebay_app_token=_optional_secret("EBAY_APP_TOKEN"),
        reddit_client_id=_optional_secret("REDDIT_CLIENT_ID"),
        reddit_client_secret=_optional_secret("REDDIT_CLIENT_SECRET"),
        reddit_user_agent=_optional_secret("REDDIT_USER_AGENT"),
        humor_reference_csv_url=_optional_secret("HUMOR_REFERENCE_CSV_URL"),
        provider_mode=os.getenv("MVP_PROVIDER_MODE", "fixture").strip().lower(),
        stop_after_stage=max(1, min(18, int(os.getenv("MVP_STOP_AFTER_STAGE", "1")))),
        trending_share=default_trending_share(),
    )


def default_trending_share() -> float:
    """Read MVP_TRENDING_SHARE. Values outside 0–1 clamp. Blank or junk stays at 0.6."""

    raw = (os.getenv("MVP_TRENDING_SHARE", "0.6") or "0.6").strip()
    try:
        value = float(raw)
    except ValueError:
        return 0.6
    return min(1.0, max(0.0, value))


def _optional_secret(name: str) -> str | None:
    """Read one credential from the environment, then Streamlit secrets.

    Environment variables win so a shell or deployed env can override a local secrets file.
    The secrets file is the same TOML Streamlit loads, which lets the worker see those values
    without importing Streamlit. A running Streamlit process is checked last.
    """

    environment = (os.getenv(name) or "").strip()
    if environment:
        return environment
    from_file = _secrets_file_value(name)
    if from_file:
        return from_file
    return _streamlit_secret_value(name)


def _secrets_file_value(name: str) -> str | None:
    """Read a flat key from `.streamlit/secrets.toml` when that file exists."""

    path = ENV_FILE.parent / ".streamlit" / "secrets.toml"
    if not path.is_file():
        return None
    try:
        import tomllib

        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError):
        return None
    return _secret_text(data.get(name) if isinstance(data, dict) else None)


def _streamlit_secret_value(name: str) -> str | None:
    """Read one key from Streamlit secrets when the app runtime is available."""

    try:
        import streamlit as st

        if name not in st.secrets:
            return None
        return _secret_text(st.secrets[name])
    except Exception:  # noqa: BLE001 - missing Streamlit secrets must not break startup.
        return None


def _secret_text(value: object) -> str | None:
    """Normalize a secret value and treat blanks as missing."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _default_openai_token_prices(model: str) -> tuple[float, float]:
    """Return standard per-million-token rates for supported model aliases."""

    normalized_model = model.casefold()
    if normalized_model.startswith("gpt-6-luna"):
        return 0.10, 0.50
    if normalized_model.startswith("gpt-5.6-luna"):
        return 0.20, 1.20
    return 0.15, 0.60


def require_mongodb_uri(settings: Settings) -> str:
    """Return the MongoDB URI or fail with an actionable configuration error."""

    if not settings.mongodb_uri:
        raise ConfigurationError("MONGODB_URI is required for database-backed execution.")
    return settings.mongodb_uri
