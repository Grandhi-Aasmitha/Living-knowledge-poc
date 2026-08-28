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

    @field_validator("tabnine_timeout_seconds")
    @classmethod
    def tabnine_timeout_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("tabnine_timeout_seconds must be positive")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
