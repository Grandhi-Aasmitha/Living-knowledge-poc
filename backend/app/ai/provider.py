from pathlib import Path
from shutil import which

from app.ai.client import AIProviderError, StructuredAIClient
from app.ai.local_rules_client import LocalRulesClient
from app.ai.model import build_ai_model
from app.ai.pydantic_ai_client import PydanticAIClient
from app.ai.tabnine_cli_client import TabnineCliClient
from app.config import Settings


def build_structured_ai_client(settings: Settings) -> StructuredAIClient:
    if settings.ai_provider == "local_rules":
        return LocalRulesClient()

    if settings.ai_provider == "tabnine_cli":
        resolved_cli_path = _resolve_executable(settings.tabnine_cli_path)
        if resolved_cli_path is None:
            raise AIProviderError("Tabnine CLI executable is not available")
        return TabnineCliClient(
            cli_path=resolved_cli_path,
            timeout_seconds=settings.tabnine_timeout_seconds,
        )

    if settings.ai_provider == "azure_openai":
        model = build_ai_model(settings)
        if model is None:
            raise AIProviderError("Azure OpenAI configuration is incomplete")
        return PydanticAIClient(model)

    raise AIProviderError("Unknown AI provider")


def _resolve_executable(cli_path: str) -> str | None:
    path = Path(cli_path)
    if path.is_absolute():
        if path.is_file():
            return str(path)
        return None
    return which(cli_path)
