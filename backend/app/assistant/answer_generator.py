import json

from app.ai.client import StructuredAIClient
from app.ai.prompts import get_assistant_answer_generation_prompt
from app.assistant.models import AnswerDraft, KnowledgeContext, context_for_prompt


class AnswerGenerator:
    def __init__(self, ai_client: StructuredAIClient) -> None:
        self._ai_client = ai_client

    async def generate(self, question: str, context: KnowledgeContext) -> AnswerDraft:
        prompt = self._build_prompt(question, context)
        return await self._ai_client.generate_structured(prompt, AnswerDraft)

    def _build_prompt(self, question: str, context: KnowledgeContext) -> str:
        payload = {
            "user_question": question,
            "knowledge_context": context_for_prompt(context),
        }
        return "\n\n".join(
            [
                get_assistant_answer_generation_prompt(),
                "Structured knowledge context:",
                json.dumps(payload, indent=2, sort_keys=True),
            ]
        )
