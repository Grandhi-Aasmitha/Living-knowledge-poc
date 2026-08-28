import json
from typing import Any

from pydantic_ai import Agent

from app.ai.models import QuestionDraft
from app.ai.prompts import get_question_generation_prompt
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.gap import KnowledgeGap


class QuestionGenerator:
    def __init__(self, model: Any) -> None:
        self._agent = Agent(
            model,
            output_type=QuestionDraft,
            instructions=get_question_generation_prompt(),
        )

    async def generate(
        self,
        gap: KnowledgeGap,
        entity: Entity,
        existing_claims: list[Claim],
    ) -> QuestionDraft:
        context = {
            "gap_type": gap.gap_type,
            "gap_description": gap.description,
            "entity": {
                "id": entity.id,
                "canonical_name": entity.canonical_name,
                "entity_type": entity.entity_type,
            },
            "existing_claims": [
                {
                    "subject_entity_id": claim.subject_entity_id,
                    "predicate": claim.predicate,
                    "object_entity_id": claim.object_entity_id,
                    "object_value": claim.object_value,
                    "status": claim.status,
                }
                for claim in existing_claims
            ],
        }
        result = await self._agent.run(json.dumps(context, sort_keys=True))
        return result.output
