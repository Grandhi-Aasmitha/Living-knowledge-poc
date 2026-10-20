import asyncio
from typing import TypeVar

from pydantic import BaseModel

from app.ai.extraction_models import ExtractedKnowledge
from app.ai.knowledge_extractor import KnowledgeExtractor
from app.documents.models import SourceChunk


T = TypeVar("T", bound=BaseModel)


def run(coro):
    return asyncio.run(coro)


class FakeStructuredAIClient:
    def __init__(self) -> None:
        self.prompt = ""
        self.response_model: type[BaseModel] | None = None

    async def generate_structured(self, prompt: str, response_model: type[T]) -> T:
        self.prompt = prompt
        self.response_model = response_model
        return response_model(
            entities=[
                {"temporary_id": "svc", "entity_type": "SERVICE", "name": "Ingestion Service"},
                {"temporary_id": "topic", "entity_type": "TOPIC", "name": "Transformed Price Topic"},
            ],
            claims=[
                {
                    "subject": "svc",
                    "predicate": "PUBLISHES_TO",
                    "object_entity": "topic",
                    "confidence": 0.9,
                    "evidence_text": "The Ingestion Service publishes to the Transformed Price Topic.",
                }
            ],
            unresolved_terms=[],
        )


def test_knowledge_extractor_passes_chunk_context_and_returns_model() -> None:
    client = FakeStructuredAIClient()
    extractor = KnowledgeExtractor(client)
    chunk = SourceChunk(
        id="chunk-1",
        version_id="version-1",
        sequence=1,
        heading_path=["Price Event Flow"],
        content="The Ingestion Service publishes to the Transformed Price Topic.",
        locator="Page 1",
        content_hash="hash",
    )

    result = run(extractor.extract(chunk, namespace="test"))

    assert isinstance(result, ExtractedKnowledge)
    assert client.response_model is ExtractedKnowledge
    assert "Price Event Flow" in client.prompt
    assert "Page 1" in client.prompt
    assert "test" in client.prompt
    assert "PUBLISHES_TO" in client.prompt
    assert "The Ingestion Service publishes to the Transformed Price Topic." in client.prompt


def test_knowledge_extractor_drops_malformed_ownership_claims() -> None:
    class OwnershipClient:
        async def generate_structured(self, prompt: str, response_model: type[T]) -> T:
            return response_model.model_validate({
                "entities": [
                    {"temporary_id": "team", "entity_type": "TEAM", "name": "Cedar Support Team"},
                    {"temporary_id": "service", "entity_type": "SERVICE", "name": "Cedar Returns Service"},
                    {"temporary_id": "record", "entity_type": "DOCUMENT", "name": "Logistics ownership record"},
                ],
                "claims": [
                    {"subject": "team", "predicate": "OWNS", "object_entity": "service", "confidence": 0.9, "evidence_text": "Cedar Support Team operates Cedar Returns Service."},
                    {"subject": "record", "predicate": "OWNS", "object_entity": "service", "confidence": 0.5, "evidence_text": "The record assigns Cedar Returns Service."},
                    {"subject": "service", "predicate": "OWNS", "object_entity": "team", "confidence": 0.5, "evidence_text": "Cedar Support Team operates Cedar Returns Service."},
                ],
            })

    chunk = SourceChunk(
        id="chunk-ownership", version_id="version-ownership", sequence=1,
        heading_path=["Ownership"], content="Cedar Support Team operates Cedar Returns Service.",
        locator=None, content_hash="hash",
    )
    result = run(KnowledgeExtractor(OwnershipClient()).extract(chunk, namespace="test"))

    assert len(result.claims) == 1
    assert result.claims[0].subject == "team"
    assert result.claims[0].object_entity == "service"
