import json
from typing import Any

from pydantic_ai import Agent

from app.ai.models import AnswerInterpretation
from app.ai.prompts import get_answer_interpretation_prompt
from app.domain.entity import Entity
from app.domain.gap import KnowledgeGap


class AnswerInterpreter:
    def __init__(self, model: Any) -> None:
        self._agent = Agent(
            model,
            output_type=AnswerInterpretation,
            instructions=get_answer_interpretation_prompt(),
        )

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
        result = await self._agent.run(json.dumps(context, sort_keys=True))
        return result.output
