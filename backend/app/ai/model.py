from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.azure import AzureProvider

from app.config import Settings


def _has_value(value: str | None) -> bool:
    return value is not None and value.strip() != ""


def build_ai_model(settings: Settings) -> OpenAIChatModel | None:
    if not _has_value(settings.azure_openai_endpoint):
        return None
    if settings.azure_openai_api_key is None or not _has_value(settings.azure_openai_api_key.get_secret_value()):
        return None
    if not _has_value(settings.azure_openai_model):
        return None

    provider = AzureProvider(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key.get_secret_value(),
    )
    return OpenAIChatModel(settings.azure_openai_model, provider=provider)
