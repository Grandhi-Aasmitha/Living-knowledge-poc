import asyncio
from typing import Any

from pydantic import BaseModel

from app.assistant.answer_generator import AnswerGenerator
from app.assistant.models import AnswerDraft, KnowledgeContext, MatchedEntity


class FakeClient:
    def __init__(self) -> None:
        self.prompt = ""

    async def generate_structured(self, prompt: str, response_model: type[BaseModel]) -> Any:
        self.prompt = prompt
        return AnswerDraft(
            answer="TSTVS Team owns Scheduler Service.",
            insufficient_knowledge=False,
            cited_claim_ids=["claim:one"],
            cited_evidence_ids=["evidence:one"],
        )


def test_answer_generator_passes_structured_context() -> None:
    client = FakeClient()
    context = KnowledgeContext(
        matched_entities=[MatchedEntity(id="entity:one", label="Scheduler Service", entity_type="SERVICE", namespace="tstvs")],
        claims=[],
    )

    draft = asyncio.run(AnswerGenerator(client).generate("Who owns Scheduler Service?", context))

    assert draft.cited_claim_ids == ["claim:one"]
    assert "knowledge_context" in client.prompt
    assert "Scheduler Service" in client.prompt
    assert "do not use model memory" in client.prompt.casefold()
