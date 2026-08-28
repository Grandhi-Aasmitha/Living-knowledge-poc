from typing import Protocol, TypeVar

from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


class StructuredAIClient(Protocol):
    async def generate_structured(self, prompt: str, response_model: type[T]) -> T:
        pass


class AIProviderError(RuntimeError):
    pass
