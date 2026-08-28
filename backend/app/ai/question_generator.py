import json

from app.ai.client import StructuredAIClient
from app.ai.models import QuestionDraft
from app.ai.prompts import get_question_generation_prompt
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.gap import KnowledgeGap


class QuestionGenerator:
    def __init__(self, ai_client: StructuredAIClient) -> None:
        self._ai_client = ai_client

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
        separator = chr(10) + chr(10)
        prompt = separator.join(
            [
                get_question_generation_prompt(),
                "Context JSON:",
                json.dumps(context, sort_keys=True),
            ]
        )
        return await self._ai_client.generate_structured(prompt, QuestionDraft)
