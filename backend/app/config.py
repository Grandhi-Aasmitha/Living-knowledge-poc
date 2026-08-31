from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPOSITORY_ROOT / ".env"


class Settings(BaseSettings):
    app_name: str = "Living Knowledge POC"
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    neo4j_database: str
    frontend_origin: str
    ai_provider: str = "tabnine_cli"
    tabnine_cli_path: str = "tabnine"
    tabnine_timeout_seconds: int = 60
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_model: str | None = None
    langgraph_checkpoint_db: str = "data/langgraph_checkpoints.db"
    upload_directory: str = "data/uploads"
    max_upload_size_mb: int = 10
    max_chunk_chars: int = 6000
    max_chunks_per_document: int = 20
    assistant_max_claims: int = 25
    assistant_max_evidence_per_claim: int = 2
    assistant_max_evidence_chars: int = 600
    assistant_max_context_chars: int = 12000

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
    )

    @field_validator("ai_provider")
    @classmethod
    def ai_provider_must_be_supported(cls, value: str) -> str:
        if value not in {"tabnine_cli", "azure_openai"}:
            raise ValueError("ai_provider must be tabnine_cli or azure_openai")
        return value

    @field_validator(
        "tabnine_timeout_seconds",
        "max_upload_size_mb",
        "max_chunk_chars",
        "max_chunks_per_document",
        "assistant_max_claims",
        "assistant_max_evidence_per_claim",
        "assistant_max_evidence_chars",
        "assistant_max_context_chars",
    )
    @classmethod
    def positive_integer_settings_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("numeric settings must be positive")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
