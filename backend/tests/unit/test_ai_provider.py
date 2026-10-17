from pydantic import SecretStr, ValidationError
import pytest

from app.ai.client import AIProviderError
from app.ai.local_rules_client import LocalRulesClient
from app.ai.provider import build_structured_ai_client
from app.ai.pydantic_ai_client import PydanticAIClient
from app.ai.tabnine_cli_client import TabnineCliClient
from app.config import Settings


def settings(**overrides) -> Settings:
    values = {
        "neo4j_uri": "bolt://localhost:7687",
        "neo4j_username": "neo4j",
        "neo4j_password": "test-password",
        "neo4j_database": "neo4j",
        "frontend_origin": "http://localhost:5173",
        "openai_api_key": None,
        "openai_model": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_tabnine_provider_builds_tabnine_client(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.provider.which", lambda path: "C:/fake/tabnine.exe")

    client = build_structured_ai_client(settings(ai_provider="tabnine_cli", tabnine_cli_path="tabnine"))

    assert isinstance(client, TabnineCliClient)
    assert client._cli_path == "C:/fake/tabnine.exe"


def test_local_rules_provider_needs_no_ai_credentials() -> None:
    assert isinstance(build_structured_ai_client(settings(ai_provider="local_rules")), LocalRulesClient)


def test_azure_provider_builds_pydantic_ai_client() -> None:
    client = build_structured_ai_client(
        settings(
            ai_provider="azure_openai",
            azure_openai_endpoint="https://example.openai.azure.com/openai/v1/",
            azure_openai_api_key=SecretStr("test-key"),
            azure_openai_model="test-model",
        )
    )

    assert isinstance(client, PydanticAIClient)


def test_openai_provider_builds_pydantic_ai_client() -> None:
    client = build_structured_ai_client(
        settings(
            ai_provider="openai",
            openai_api_key=SecretStr("test-key"),
            openai_model="test-model",
        )
    )

    assert isinstance(client, PydanticAIClient)
    assert client._model.model_name == "test-model"


@pytest.mark.parametrize(
    ("key", "model"),
    [
        (None, "test-model"),
        (SecretStr("test-key"), None),
        (SecretStr("   "), "test-model"),
        (SecretStr("test-key"), "   "),
    ],
)
def test_incomplete_openai_config_is_provider_unavailable(key, model) -> None:
    with pytest.raises(AIProviderError, match="OPENAI_API_KEY and OPENAI_MODEL"):
        build_structured_ai_client(settings(ai_provider="openai", openai_api_key=key, openai_model=model))


def test_invalid_provider_is_rejected_by_settings() -> None:
    with pytest.raises(ValidationError):
        settings(ai_provider="unknown")


def test_incomplete_azure_config_is_provider_unavailable() -> None:
    with pytest.raises(AIProviderError):
        build_structured_ai_client(settings(ai_provider="azure_openai"))


def test_incomplete_azure_config_does_not_block_tabnine(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.provider.which", lambda path: "C:/fake/tabnine.exe")

    client = build_structured_ai_client(settings(ai_provider="tabnine_cli"))

    assert isinstance(client, TabnineCliClient)


def test_missing_tabnine_cli_is_provider_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.provider.which", lambda path: None)

    with pytest.raises(AIProviderError):
        build_structured_ai_client(settings(ai_provider="tabnine_cli"))
