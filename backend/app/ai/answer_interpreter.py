import json

from app.ai.client import StructuredAIClient
from app.ai.models import AnswerInterpretation
from app.ai.prompts import get_answer_interpretation_prompt
from app.domain.entity import Entity
from app.domain.gap import KnowledgeGap


class AnswerInterpreter:
    def __init__(self, ai_client: StructuredAIClient) -> None:
        self._ai_client = ai_client

    async def interpret(
        self,
        question: str,
        answer: str,
        gap: KnowledgeGap,
        entity: Entity,
    ) -> AnswerInterpretation:
        context = {
            "question": question,
            "answer": answer,
            "gap": {
                "id": gap.id,
                "gap_type": gap.gap_type,
                "description": gap.description,
            },
            "entity": {
                "id": entity.id,
                "canonical_name": entity.canonical_name,
                "entity_type": entity.entity_type,
            },
        }
        separator = chr(10) + chr(10)
        prompt = separator.join(
            [
                get_answer_interpretation_prompt(),
                "Context JSON:",
                json.dumps(context, sort_keys=True),
            ]
        )
        return await self._ai_client.generate_structured(prompt, AnswerInterpretation)
