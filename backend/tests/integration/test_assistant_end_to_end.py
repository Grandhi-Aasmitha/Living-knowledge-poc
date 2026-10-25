import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

import pytest

from app.assistant.answer_generator import AnswerGenerator
from app.assistant.models import AnswerDraft, KnowledgeQueryPlan, QueryDirection
from app.assistant.query_planner import QueryPlanner
from app.assistant.service import KnowledgeAssistantService
from app.config import get_settings
from app.db.neo4j import Neo4jClient
from app.db.schema import ensure_schema
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.enums import ClaimStatus, SourceType
from app.domain.evidence import Evidence
from app.domain.source import KnowledgeSource
from app.repositories.claim_repository import ClaimRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.knowledge_query_repository import KnowledgeQueryRepository
from app.repositories.source_repository import SourceRepository

pytestmark = pytest.mark.integration
T = TypeVar("T")
NAMESPACE = "phase9-eval"


class FakeStructuredAIClient:
    async def generate_structured(self, prompt: str, response_model):
        if response_model is KnowledgeQueryPlan:
            if "Which team owns the service that produces Eval Topic" in prompt:
                return KnowledgeQueryPlan(entity_names=["Eval Topic"], predicates=["PRODUCES", "OWNS"], direction=QueryDirection.BOTH, answer_entity_types=["TEAM"])
            if "Who owns Eval Service" in prompt:
                return KnowledgeQueryPlan(entity_names=["Eval Service"], predicates=["OWNS"], direction=QueryDirection.INCOMING)
            if "What consumes Eval Topic" in prompt:
                return KnowledgeQueryPlan(entity_names=["Eval Topic"], predicates=["CONSUMES"], direction=QueryDirection.INCOMING)
            if "What does Eval Service produce" in prompt:
                return KnowledgeQueryPlan(entity_names=["Eval Service"], predicates=["PRODUCES"], direction=QueryDirection.OUTGOING)
            return KnowledgeQueryPlan(entity_names=["Eval Database"], predicates=["WRITES_TO"], direction=QueryDirection.INCOMING)
        if '"user_question": "Which team owns the service that produces Eval Topic?"' in prompt:
            return AnswerDraft(
                answer="Eval Team owns Eval Service, which produces Eval Topic.", insufficient_knowledge=False,
                cited_claim_ids=["phase9-eval:claim:owns", "phase9-eval:claim:produces"],
                cited_evidence_ids=["phase9-eval:evidence:owns", "phase9-eval:evidence:produces"],
            )
        if '"user_question": "Who owns Eval Service?"' in prompt:
            return AnswerDraft(answer="Eval Team owns Eval Service.", insufficient_knowledge=False, cited_claim_ids=["phase9-eval:claim:owns"], cited_evidence_ids=["phase9-eval:evidence:owns"])
        if '"user_question": "What consumes Eval Topic?"' in prompt:
            return AnswerDraft(answer="Eval Consumer consumes Eval Topic.", insufficient_knowledge=False, cited_claim_ids=["phase9-eval:claim:consumes"], cited_evidence_ids=["phase9-eval:evidence:consumes"])
        if '"user_question": "What does Eval Service produce?"' in prompt:
            return AnswerDraft(answer="Eval Service produces Eval Topic.", insufficient_knowledge=False, cited_claim_ids=["phase9-eval:claim:produces"], cited_evidence_ids=["phase9-eval:evidence:produces"])
        return AnswerDraft(answer="I don't have enough source-backed knowledge to answer that.", insufficient_knowledge=True)


def run_with_client(test_body: Callable[[Neo4jClient], Awaitable[T]]) -> T:
    async def runner() -> T:
        settings = get_settings()
        client = Neo4jClient(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password, settings.neo4j_database)
        if not await client.ping():
            await client.close()
            pytest.skip("Neo4j is not available")
        try:
            await ensure_schema(client)
            await cleanup(client)
            await fixture(client)
            return await test_body(client)
        finally:
            await cleanup(client)
            await client.close()

    return asyncio.run(runner())


async def cleanup(client: Neo4jClient) -> None:
    async with client.session() as session:
        await session.run("MATCH (evidence:Evidence) WHERE evidence.id STARTS WITH 'phase9-eval:' DETACH DELETE evidence")
        await session.run("MATCH (claim:Claim) WHERE claim.id STARTS WITH 'phase9-eval:' DETACH DELETE claim")
        await session.run("MATCH (source:KnowledgeSource) WHERE source.id STARTS WITH 'phase9-eval:' DETACH DELETE source")
        await session.run("MATCH (entity:Entity {namespace: $namespace}) DETACH DELETE entity", namespace=NAMESPACE)


async def fixture(client: Neo4jClient) -> None:
    entity_repository = EntityRepository(client)
    for entity in [
        Entity(id="phase9-eval:team:eval-team", entity_type="TEAM", canonical_name="Eval Team", namespace=NAMESPACE),
        Entity(id="phase9-eval:service:eval-service", entity_type="SERVICE", canonical_name="Eval Service", namespace=NAMESPACE, aliases=["Eval App"]),
        Entity(id="phase9-eval:topic:eval-topic", entity_type="TOPIC", canonical_name="Eval Topic", namespace=NAMESPACE),
        Entity(id="phase9-eval:service:eval-consumer", entity_type="SERVICE", canonical_name="Eval Consumer", namespace=NAMESPACE),
        Entity(id="phase9-eval:database:eval-database", entity_type="DATABASE", canonical_name="Eval Database", namespace=NAMESPACE),
    ]:
        await entity_repository.create(entity)
    await SourceRepository(client).create(KnowledgeSource(id="phase9-eval:source", source_type=SourceType.SYSTEM, title="Phase 9 Evaluation Fixture"))
    claim_repository = ClaimRepository(client)
    for claim, evidence_id, excerpt in [
        (Claim(id="phase9-eval:claim:owns", subject_entity_id="phase9-eval:team:eval-team", predicate="OWNS", object_entity_id="phase9-eval:service:eval-service", status=ClaimStatus.CONFIRMED, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)), "phase9-eval:evidence:owns", "Eval Team owns Eval Service."),
        (Claim(id="phase9-eval:claim:produces", subject_entity_id="phase9-eval:service:eval-service", predicate="PRODUCES", object_entity_id="phase9-eval:topic:eval-topic", status=ClaimStatus.CONFIRMED, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)), "phase9-eval:evidence:produces", "Eval Service produces Eval Topic."),
        (Claim(id="phase9-eval:claim:consumes", subject_entity_id="phase9-eval:service:eval-consumer", predicate="CONSUMES", object_entity_id="phase9-eval:topic:eval-topic", status=ClaimStatus.CONFIRMED, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)), "phase9-eval:evidence:consumes", "Eval Consumer consumes Eval Topic."),
    ]:
        await claim_repository.create(claim)
        await claim_repository.add_evidence(Evidence(id=evidence_id, claim_id=claim.id, source_id="phase9-eval:source", excerpt=excerpt))


def service(client: Neo4jClient) -> KnowledgeAssistantService:
    ai_client = FakeStructuredAIClient()
    return KnowledgeAssistantService(
        query_planner=QueryPlanner(ai_client),
        repository=KnowledgeQueryRepository(client),
        answer_generator=AnswerGenerator(ai_client),
        max_claims=25,
        max_evidence_per_claim=2,
        max_evidence_chars=600,
        max_context_chars=12000,
    )


def test_assistant_answers_source_backed_questions_and_refuses_unknown() -> None:
    async def body(client: Neo4jClient) -> None:
        assistant = service(client)

        owner = await assistant.ask("Who owns Eval Service?", NAMESPACE)
        consumer = await assistant.ask("What consumes Eval Topic?", NAMESPACE)
        producer = await assistant.ask("What does Eval Service produce?", NAMESPACE)
        composed = await assistant.ask("Which team owns the service that produces Eval Topic?", NAMESPACE)
        unknown = await assistant.ask("What writes to Eval Database?", NAMESPACE)

        assert owner.knowledge_status == "CONFIRMED"
        assert {citation.claim_id for citation in owner.citations} == {"phase9-eval:claim:owns"}
        assert {citation.claim_id for citation in consumer.citations} == {"phase9-eval:claim:consumes"}
        assert {citation.claim_id for citation in producer.citations} == {"phase9-eval:claim:produces"}
        assert {citation.claim_id for citation in composed.citations} == {"phase9-eval:claim:owns", "phase9-eval:claim:produces"}
        assert unknown.insufficient_knowledge is True
        assert unknown.citations == []

    run_with_client(body)
