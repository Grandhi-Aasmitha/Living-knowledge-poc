import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypeVar

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.ai.models import AnswerInterpretation, QuestionDraft
from app.completeness.service import GapDetectionService
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
from app.repositories.completeness_repository import CompletenessRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.gap_repository import GapRepository
from app.repositories.source_repository import SourceRepository
from app.workflows.curation import CurationWorkflow

pytestmark = pytest.mark.integration
T = TypeVar("T")
NAMESPACE = "phase6-life-test"


def run_with_client(test_body: Callable[[Neo4jClient], Awaitable[T]]) -> T:
    async def runner() -> T:
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

        try:
            await ensure_schema(client)
            await cleanup(client)
            return await test_body(client)
        finally:
            await cleanup(client)
            await client.close()

    return asyncio.run(runner())


async def cleanup(client: Neo4jClient) -> None:
    async with client.session() as session:
        await session.run(
            """
            MATCH (gap:KnowledgeGap)-[:ABOUT]->(entity:Entity {namespace: $namespace})
            DETACH DELETE gap
            """,
            namespace=NAMESPACE,
        )
        await session.run("MATCH (evidence:Evidence) WHERE evidence.id STARTS WITH 'phase6:life:' OR evidence.id STARTS WITH 'curation:evidence:phase6-life-' DETACH DELETE evidence")
        await session.run("MATCH (claim:Claim) WHERE claim.id STARTS WITH 'phase6:life:' OR claim.id STARTS WITH 'curation:claim:phase6-life-' DETACH DELETE claim")
        await session.run("MATCH (source:KnowledgeSource) WHERE source.id STARTS WITH 'phase6:life:' OR source.id STARTS WITH 'human:curation:phase6-life-' DETACH DELETE source")
        await session.run("MATCH (entity:Entity {namespace: $namespace}) DETACH DELETE entity", namespace=NAMESPACE)


async def create_entity(client: Neo4jClient, entity_id: str, entity_type: str, name: str) -> Entity:
    return await EntityRepository(client).create(
        Entity(id=entity_id, entity_type=entity_type, canonical_name=name, namespace=NAMESPACE)
    )


async def create_claim_with_evidence(
    client: Neo4jClient,
    claim_id: str,
    subject: Entity,
    predicate: str,
    object_entity: Entity,
    status: ClaimStatus = ClaimStatus.CONFIRMED,
) -> Claim:
    source = await SourceRepository(client).create(
        KnowledgeSource(
            id=f"phase6:life:source:{claim_id}",
            source_type=SourceType.SYSTEM,
            title="Synthetic lifecycle source",
        )
    )
    claim = await ClaimRepository(client).create(
        Claim(
            id=claim_id,
            subject_entity_id=subject.id,
            predicate=predicate,
            object_entity_id=object_entity.id,
            status=status,
        )
    )
    await ClaimRepository(client).add_evidence(
        Evidence(
            id=f"phase6:life:evidence:{claim_id}",
            claim_id=claim.id,
            source_id=source.id,
            excerpt="Synthetic evidence.",
        )
    )
    return claim


async def detect(client: Neo4jClient):
    return await GapDetectionService(CompletenessRepository(client), GapRepository(client)).detect(NAMESPACE)


def test_detection_idempotency_auto_resolution_reopen_and_manual_gap_safety() -> None:
    async def body(client: Neo4jClient) -> None:
        topic = await create_entity(client, "phase6:life:topic:dispatch", "TOPIC", "Dispatch Topic")
        producer = await create_entity(client, "phase6:life:service:producer", "SERVICE", "Producer Service")
        consumer = await create_entity(client, "phase6:life:service:consumer", "SERVICE", "Consumer Service")
        team = await create_entity(client, "phase6:life:team:platform", "TEAM", "Platform Team")
        await create_claim_with_evidence(client, "phase6:life:claim:producer-owner", team, "OWNS", producer)
        await create_claim_with_evidence(client, "phase6:life:claim:consumer-owner", team, "OWNS", consumer)
        await create_claim_with_evidence(client, "phase6:life:claim:producer", producer, "PRODUCES", topic)

        first = await detect(client)
        second = await detect(client)
        assert first.gaps_created == 1
        assert second.gaps_created == 0
        assert second.gaps_existing == 1

        await create_claim_with_evidence(client, "phase6:life:claim:consumer", consumer, "CONSUMES", topic)
        resolved = await detect(client)
        assert resolved.gaps_resolved == 1
        assert resolved.open_automatic_gaps == 0

        async with client.session() as session:
            await session.run(
                "MATCH (claim:Claim {id: $id}) SET claim.status = 'RETIRED'",
                id="phase6:life:claim:consumer",
            )
        reopened = await detect(client)
        assert reopened.gaps_reopened == 1

        await GapRepository(client).create(
            KnowledgeGap(
                id="phase6:life:manual:gap",
                entity_id=topic.id,
                gap_type="MISSING_CONSUMER",
                description="Manual consumer gap",
                priority=GapPriority.HIGH,
            )
        )
        async with client.session() as session:
            await session.run(
                "MATCH (gap:KnowledgeGap) WHERE gap.id STARTS WITH 'auto:gap:missing-consumer-v1:' SET gap.status = 'RESOLVED'"
            )
        manual_safe = await detect(client)
        manual_gap = await GapRepository(client).get("phase6:life:manual:gap")
        assert manual_safe.gaps_reopened == 1
        assert manual_gap is not None
        assert manual_gap.status == "OPEN"

    run_with_client(body)


class FakeQuestionGenerator:
    async def generate(self, gap, entity, existing_claims) -> QuestionDraft:
        return QuestionDraft(question=f"Which team owns {entity.canonical_name}?")


class FakeOwnerAnswerInterpreter:
    async def interpret(self, question, answer, gap, entity) -> AnswerInterpretation:
        if answer.casefold().strip() == "tstvs team":
            return AnswerInterpretation(can_resolve=True, entity_name="TSTVS Team", entity_type="TEAM")
        return AnswerInterpretation(can_resolve=False, reason="No team was identified.")


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
        answer_interpreter=FakeOwnerAnswerInterpreter(),
        checkpointer=checkpointer,
    )
    workflow._test_checkpointer_context = checkpointer_context
    return workflow


async def close_workflow(workflow: CurationWorkflow) -> None:
    await workflow._test_checkpointer_context.__aexit__(None, None, None)


def test_end_to_end_missing_owner_curation_resolves_gap_and_prevents_redetection() -> None:
    async def body(client: Neo4jClient) -> None:
        service = await create_entity(client, "phase6:life:service:scheduler", "SERVICE", "Scheduler Service")

        scan = await detect(client)
        assert scan.gaps_created == 1
        owner_gap = next(
            gap
            for gap in await GapRepository(client).list_automatic_for_namespace(NAMESPACE)
            if gap.entity_id == service.id and gap.gap_type == "MISSING_OWNER"
        )

        with TemporaryDirectory() as temp_dir:
            workflow = await build_workflow(client, Path(temp_dir) / "checkpoints.db")
            start = await workflow.start("phase6-life-owner-workflow", owner_gap.id)
            assert start["status"] == "WAITING_FOR_HUMAN"
            result = await workflow.answer("phase6-life-owner-workflow", "TSTVS Team")
            assert result["status"] == "RESOLVED"
            assert result["entity_id"] == "phase6-life-test:team:tstvs-team"

            claim = await ClaimRepository(client).get("curation:claim:phase6-life-owner-workflow")
            gap = await GapRepository(client).get(owner_gap.id)
            assert claim is not None
            assert claim.predicate == "OWNS"
            assert claim.status == ClaimStatus.CONFIRMED
            assert claim.object_entity_id == service.id
            assert gap is not None
            assert gap.status == "RESOLVED"

            rescan = await detect(client)
            assert rescan.gaps_reopened == 0
            assert all(
                not (gap.entity_id == service.id and gap.gap_type == "MISSING_OWNER" and gap.status == "OPEN")
                for gap in await GapRepository(client).list_automatic_for_namespace(NAMESPACE)
            )
            await close_workflow(workflow)

    run_with_client(body)
