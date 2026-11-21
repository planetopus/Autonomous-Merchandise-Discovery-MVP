"""Tests for model-specific OpenAI reasoning and usage-estimate configuration."""

from pathlib import Path

from merchandise_discovery.shared import configuration


def _isolate_environment(monkeypatch) -> None:
    """Prevent developer-local dotenv values from changing configuration expectations."""

    monkeypatch.setattr(configuration, "ENV_FILE", Path("missing-test-env"))
    monkeypatch.setattr(configuration, "load_dotenv", lambda **_: None)
    for name in (
        "OPENAI_REASONING_MODEL",
        "OPENAI_REASONING_EFFORT",
        "OPENAI_INPUT_PRICE_PER_MILLION",
        "OPENAI_OUTPUT_PRICE_PER_MILLION",
    ):
        monkeypatch.delenv(name, raising=False)


def test_gpt6_luna_defaults_to_medium_effort_and_current_token_rates(monkeypatch) -> None:
    """GPT-6 Luna receives its documented effort default and standard token-price defaults."""

    _isolate_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_REASONING_MODEL", "gpt-6-luna")

    settings = configuration.load_settings()

    assert settings.openai_reasoning_model == "gpt-6-luna"
    assert settings.openai_reasoning_effort == "medium"
    assert settings.openai_input_price_per_million == 0.10
    assert settings.openai_output_price_per_million == 0.50


def test_explicit_openai_price_overrides_take_precedence(monkeypatch) -> None:
    """Deliberate custom pricing remains authoritative over model-based defaults."""

    _isolate_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_REASONING_MODEL", "gpt-6-luna")
    monkeypatch.setenv("OPENAI_INPUT_PRICE_PER_MILLION", "0.12")
    monkeypatch.setenv("OPENAI_OUTPUT_PRICE_PER_MILLION", "0.55")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "low")

    settings = configuration.load_settings()

    assert settings.openai_reasoning_effort == "low"
    assert settings.openai_input_price_per_million == 0.12
    assert settings.openai_output_price_per_million == 0.55


def test_reddit_credentials_come_from_the_environment(monkeypatch) -> None:
    """Reddit OAuth settings are optional and read without logging the secret."""

    _isolate_environment(monkeypatch)
    monkeypatch.setenv("REDDIT_CLIENT_ID", "app-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "app-secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "sticker-research/0.1")

    settings = configuration.load_settings()

    assert settings.reddit_client_id == "app-id"
    assert settings.reddit_client_secret == "app-secret"
    assert settings.reddit_user_agent == "sticker-research/0.1"


def test_streamlit_secrets_file_fills_blank_reddit_settings(monkeypatch, tmp_path: Path) -> None:
    """A local Streamlit secrets file supplies Reddit credentials when the env is empty."""

    _isolate_environment(monkeypatch)
    for name in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT", "ETSY_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    secrets = tmp_path / ".streamlit"
    secrets.mkdir()
    (secrets / "secrets.toml").write_text(
        'REDDIT_CLIENT_ID = "file-id"\n'
        'REDDIT_CLIENT_SECRET = "file-secret"\n'
        'REDDIT_USER_AGENT = "file-agent/0.1"\n'
        'ETSY_API_KEY = "etsy-key"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(configuration, "ENV_FILE", tmp_path / ".env")

    settings = configuration.load_settings()

    assert settings.reddit_client_id == "file-id"
    assert settings.reddit_client_secret == "file-secret"
    assert settings.reddit_user_agent == "file-agent/0.1"
    assert settings.etsy_api_key == "etsy-key"
