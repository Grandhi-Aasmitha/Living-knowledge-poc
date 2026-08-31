import json

from app.ai.client import StructuredAIClient
from app.ai.prompts import get_assistant_query_planning_prompt
from app.assistant.models import KnowledgeQueryPlan
from app.domain.ontology import get_allowed_predicates


class QueryPlanner:
    def __init__(self, ai_client: StructuredAIClient) -> None:
        self._ai_client = ai_client

    async def plan(self, question: str) -> KnowledgeQueryPlan:
        prompt = self._build_prompt(question)
        return await self._ai_client.generate_structured(prompt, KnowledgeQueryPlan)

    def _build_prompt(self, question: str) -> str:
        context = {
            "allowed_predicates": sorted(get_allowed_predicates()),
            "user_question": question,
        }
        return "\n\n".join(
            [
                get_assistant_query_planning_prompt(),
                "Controlled retrieval context:",
                json.dumps(context, indent=2, sort_keys=True),
            ]
        )
