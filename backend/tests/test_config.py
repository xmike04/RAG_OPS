from pydantic import SecretStr
from pytest import MonkeyPatch

from ragops.config import Settings
from ragops.services.query import LocalGroundedGenerator, build_generator


def test_default_settings_are_credential_free() -> None:
    settings = Settings(_env_file=None)

    assert settings.api_key is None
    assert settings.generation_provider == "local"
    assert isinstance(build_generator(settings), LocalGroundedGenerator)


def test_cors_origins_accept_comma_separated_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("RAGOPS_CORS_ORIGINS", "https://console.example,https://admin.example")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["https://console.example", "https://admin.example"]


def test_remote_generator_requires_configuration() -> None:
    settings = Settings(generation_provider="openai-compatible", _env_file=None)

    try:
        build_generator(settings)
    except ValueError as exc:
        assert "OPENAI_COMPATIBLE" in str(exc)
    else:
        raise AssertionError("remote provider must reject missing endpoint and API key")

    configured = settings.model_copy(
        update={
            "openai_compatible_base_url": "https://llm.example.test/v1",
            "openai_compatible_api_key": SecretStr("test-key"),
        }
    )
    assert build_generator(configured).provider == "openai-compatible"
