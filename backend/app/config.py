from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
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
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_model: str | None = None
    langgraph_checkpoint_db: str = "data/langgraph_checkpoints.db"

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
