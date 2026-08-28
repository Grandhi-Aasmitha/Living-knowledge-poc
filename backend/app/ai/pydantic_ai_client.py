from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent

from app.ai.client import AIProviderError


T = TypeVar("T", bound=BaseModel)


class PydanticAIClient:
    def __init__(self, model: Any) -> None:
        self._model = model

    async def generate_structured(self, prompt: str, response_model: type[T]) -> T:
        try:
            agent = Agent(self._model, output_type=response_model)
            result = await agent.run(prompt)
            return result.output
        except Exception as error:
            raise AIProviderError("PydanticAI provider failed to generate structured output") from error
