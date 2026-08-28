import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.ai.models import AnswerInterpretation, QuestionDraft
from app.config import get_settings
from app.db.neo4j import Neo4jClient
from app.db.schema import ensure_schema
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.enums import ClaimStatus, GapPriority, SourceType
from app.domain.evidence import Evidence
from app.domain.gap import KnowledgeGap
from app.domain.source import KnowledgeSource
from app.repositories.claim_repository import ClaimRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.gap_repository import GapRepository
from app.repositories.source_repository import SourceRepository
from app.workflows.curation import CurationWorkflow

pytestmark = pytest.mark.integration


def run(coro):
    return asyncio.run(coro)


class FakeQuestionGenerator:
    async def generate(self, gap, entity, existing_claims) -> QuestionDraft:
        return QuestionDraft(question="Which service currently consumes Scheduled Dispatch?")


class FakeAnswerInterpreter:
    async def interpret(self, question, answer, gap, entity) -> AnswerInterpretation:
        if answer.casefold().strip() == "scheduler service":
            return AnswerInterpretation(
                can_resolve=True,
                entity_name="Scheduler Service",
                entity_type="SERVICE",
            )
        return AnswerInterpretation(can_resolve=False, reason="The answer does not identify a consumer.")


async def make_client() -> Neo4jClient:
    settings = get_settings()
    client = Neo4jClient(
        uri=settings.neo4j_uri,
        username=settings.neo4j_username,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
    )
    if not await client.ping():
        await client.close()
        pytest.skip("Neo4j is not available")
    await ensure_schema(client)
    return client


async def cleanup(client: Neo4jClient) -> None:
    async with client.session() as session:
        await session.run("MATCH (gap:KnowledgeGap) WHERE gap.id STARTS WITH 'test:' DETACH DELETE gap")
        await session.run("MATCH (evidence:Evidence) WHERE evidence.id STARTS WITH 'test:' OR evidence.id STARTS WITH 'curation:evidence:test-' DETACH DELETE evidence")
        await session.run("MATCH (claim:Claim) WHERE claim.id STARTS WITH 'test:' OR claim.id STARTS WITH 'curation:claim:test-' DETACH DELETE claim")
        await session.run("MATCH (source:KnowledgeSource) WHERE source.id STARTS WITH 'test:' OR source.id STARTS WITH 'human:curation:test-' DETACH DELETE source")
        await session.run("MATCH (entity:Entity) WHERE entity.id STARTS WITH 'test:' DETACH DELETE entity")


async def build_workflow(client: Neo4jClient, checkpoint_path: Path) -> CurationWorkflow:
    checkpointer_context = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
    checkpointer = await checkpointer_context.__aenter__()
    await checkpointer.setup()
    workflow = CurationWorkflow(
        entity_repository=EntityRepository(client),
        claim_repository=ClaimRepository(client),
        source_repository=SourceRepository(client),
        gap_repository=GapRepository(client),
        question_generator=FakeQuestionGenerator(),
        answer_interpreter=FakeAnswerInterpreter(),
        checkpointer=checkpointer,
    )
    workflow._test_checkpointer_context = checkpointer_context
    return workflow


async def close_workflow(workflow: CurationWorkflow) -> None:
    await workflow._test_checkpointer_context.__aexit__(None, None, None)


async def seed_test_gap(client: Neo4jClient) -> None:
    entity_repository = EntityRepository(client)
    claim_repository = ClaimRepository(client)
    source_repository = SourceRepository(client)
    gap_repository = GapRepository(client)

    scheduled_dispatch = await entity_repository.create(
        Entity(
            id="test:concept:scheduled-dispatch",
            entity_type="BUSINESS_CONCEPT",
            canonical_name="Scheduled Dispatch",
            namespace="test",
        )
    )
    aggregator = await entity_repository.create(
        Entity(
            id="test:service:aggregator",
            entity_type="SERVICE",
            canonical_name="Aggregator Service",
            namespace="test",
        )
    )
    source = await source_repository.create(
        KnowledgeSource(
            id="test:source:curation-e2e",
            source_type=SourceType.SYSTEM,
            title="Curation E2E Test",
        )
    )
    claim = await claim_repository.create(
        Claim(
            id="test:claim:aggregator-produces-scheduled-dispatch",
            subject_entity_id=aggregator.id,
            predicate="PRODUCES",
            object_entity_id=scheduled_dispatch.id,
            status=ClaimStatus.CONFIRMED,
        )
    )
    await claim_repository.add_evidence(
        Evidence(
            id="test:evidence:aggregator-produces-scheduled-dispatch",
            claim_id=claim.id,
            source_id=source.id,
            excerpt="Aggregator Service produces Scheduled Dispatch.",
        )
    )
    await gap_repository.create(
        KnowledgeGap(
            id="test:gap:scheduled-dispatch-missing-consumer",
            entity_id=scheduled_dispatch.id,
            gap_type="MISSING_CONSUMER",
            description="The consumer of Scheduled Dispatch is currently unknown.",
            priority=GapPriority.HIGH,
        )
    )


def test_curation_end_to_end_with_checkpoint_restart_and_idempotency() -> None:
    async def scenario() -> None:
        client = await make_client()
        try:
            await cleanup(client)
            await seed_test_gap(client)

            with TemporaryDirectory() as temp_dir:
                checkpoint_path = Path(temp_dir) / "curation-checkpoints.db"
                workflow = await build_workflow(client, checkpoint_path)
                start = await workflow.start(
                    workflow_id="test-workflow-e2e",
                    gap_id="test:gap:scheduled-dispatch-missing-consumer",
                )
                assert start["status"] == "WAITING_FOR_HUMAN"
                assert "Scheduled Dispatch" in start["question"]
                await close_workflow(workflow)

                restarted_workflow = await build_workflow(client, checkpoint_path)
                result = await restarted_workflow.answer("test-workflow-e2e", "Scheduler Service")
                assert result["status"] == "RESOLVED"
                assert result["entity_id"] == "test:service:scheduler-service"
                assert result["claim_id"] == "curation:claim:test-workflow-e2e"

                entity_repository = EntityRepository(client)
                claim_repository = ClaimRepository(client)
                source_repository = SourceRepository(client)
                gap_repository = GapRepository(client)

                scheduler = await entity_repository.get("test:service:scheduler-service")
                assert scheduler is not None
                assert scheduler.canonical_name == "Scheduler Service"

                claim = await claim_repository.get("curation:claim:test-workflow-e2e")
                assert claim is not None
                assert claim.status == ClaimStatus.CONFIRMED
                assert claim.predicate == "CONSUMES"
                assert claim.subject_entity_id == scheduler.id
                assert claim.object_entity_id == "test:concept:scheduled-dispatch"
                assert claim.confidence == 1.0

                source = await source_repository.get("human:curation:test-workflow-e2e")
                assert source is not None
                assert source.source_type == SourceType.HUMAN

                gap = await gap_repository.get("test:gap:scheduled-dispatch-missing-consumer")
                assert gap is not None
                assert gap.status == "RESOLVED"
                open_gap_ids = {item.id for item in await gap_repository.list_open()}
                assert gap.id not in open_gap_ids

                async with client.session() as session:
                    linked = await (
                        await session.run(
                            """
                            MATCH (:Claim {id: $claim_id})-[:SUPPORTED_BY]->(evidence:Evidence {id: $evidence_id})
                            MATCH (evidence)-[:FROM_SOURCE]->(:KnowledgeSource {id: $source_id})
                            RETURN evidence.excerpt AS excerpt, count(evidence) AS count
                            """,
                            claim_id="curation:claim:test-workflow-e2e",
                            evidence_id="curation:evidence:test-workflow-e2e",
                            source_id="human:curation:test-workflow-e2e",
                        )
                    ).single()
                    duplicates = await (
                        await session.run(
                            """
                            MATCH (entity:Entity {id: 'test:service:scheduler-service'})
                            WITH count(entity) AS entities
                            MATCH (claim:Claim {id: 'curation:claim:test-workflow-e2e'})
                            WITH entities, count(claim) AS claims
                            MATCH (source:KnowledgeSource {id: 'human:curation:test-workflow-e2e'})
                            WITH entities, claims, count(source) AS sources
                            MATCH (evidence:Evidence {id: 'curation:evidence:test-workflow-e2e'})
                            RETURN entities, claims, sources, count(evidence) AS evidence
                            """
                        )
                    ).single()

                assert linked is not None
                assert linked["count"] == 1
                assert linked["excerpt"] == "Scheduler Service"

                state = {
                    "workflow_id": "test-workflow-e2e",
                    "gap_id": "test:gap:scheduled-dispatch-missing-consumer",
                    "gap_entity_id": "test:concept:scheduled-dispatch",
                    "gap_entity_name": "Scheduled Dispatch",
                    "namespace": "test",
                    "question": start["question"],
                    "engineer_answer": "Scheduler Service",
                    "interpretation": {
                        "can_resolve": True,
                        "entity_name": "Scheduler Service",
                        "entity_type": "SERVICE",
                        "reason": None,
                    },
                    "claim_candidate": {
                        "subject_entity_id": "test:service:scheduler-service",
                        "predicate": "CONSUMES",
                        "object_entity_id": "test:concept:scheduled-dispatch",
                        "confidence": 1.0,
                    },
                }
                await restarted_workflow.persist_knowledge_for_retry(state)

                async with client.session() as session:
                    after_retry = await (
                        await session.run(
                            """
                            MATCH (entity:Entity {id: 'test:service:scheduler-service'})
                            WITH count(entity) AS entities
                            MATCH (claim:Claim {id: 'curation:claim:test-workflow-e2e'})
                            WITH entities, count(claim) AS claims
                            MATCH (source:KnowledgeSource {id: 'human:curation:test-workflow-e2e'})
                            WITH entities, claims, count(source) AS sources
                            MATCH (evidence:Evidence {id: 'curation:evidence:test-workflow-e2e'})
                            RETURN entities, claims, sources, count(evidence) AS evidence
                            """
                        )
                    ).single()

                assert duplicates is not None
                assert after_retry is not None
                assert dict(duplicates) == dict(after_retry) == {
                    "entities": 1,
                    "claims": 1,
                    "sources": 1,
                    "evidence": 1,
                }
                await close_workflow(restarted_workflow)
        finally:
            await cleanup(client)
            await client.close()

    run(scenario())
