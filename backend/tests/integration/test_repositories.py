import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

import pytest

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

pytestmark = pytest.mark.integration
T = TypeVar("T")


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
            return await test_body(client)
        finally:
            await _cleanup_test_records(client)
            await client.close()

    return asyncio.run(runner())


async def _cleanup_test_records(client: Neo4jClient) -> None:
    async with client.session() as session:
        await session.run("MATCH (gap:KnowledgeGap) WHERE gap.id STARTS WITH 'test:' DETACH DELETE gap")
        await session.run("MATCH (evidence:Evidence) WHERE evidence.id STARTS WITH 'test:' DETACH DELETE evidence")
        await session.run("MATCH (claim:Claim) WHERE claim.id STARTS WITH 'test:' DETACH DELETE claim")
        await session.run("MATCH (source:KnowledgeSource) WHERE source.id STARTS WITH 'test:' DETACH DELETE source")
        await session.run("MATCH (entity:Entity) WHERE entity.id STARTS WITH 'test:' DETACH DELETE entity")


def _entity(entity_id: str, entity_type: str = "SERVICE") -> Entity:
    return Entity(
        id=entity_id,
        entity_type=entity_type,
        canonical_name=entity_id,
        namespace="test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_ensure_schema_can_run_twice() -> None:
    async def body(client: Neo4jClient) -> None:
        await ensure_schema(client)
        await ensure_schema(client)

    run_with_client(body)


def test_entity_create_get_works() -> None:
    async def body(client: Neo4jClient) -> None:
        repository = EntityRepository(client)
        entity = await repository.create(_entity("test:entity:create-get"))

        found = await repository.get(entity.id)

        assert found == entity

    run_with_client(body)


def test_repeated_entity_create_does_not_duplicate() -> None:
    async def body(client: Neo4jClient) -> None:
        repository = EntityRepository(client)
        entity = _entity("test:entity:idempotent")

        await repository.create(entity)
        await repository.create(entity)

        async with client.session() as session:
            result = await session.run(
                "MATCH (entity:Entity {id: $id}) RETURN count(entity) AS count",
                id=entity.id,
            )
            record = await result.single()

        assert record is not None
        assert record["count"] == 1

    run_with_client(body)


def test_entity_valued_claim_creation_works() -> None:
    async def body(client: Neo4jClient) -> None:
        entity_repository = EntityRepository(client)
        claim_repository = ClaimRepository(client)
        subject = await entity_repository.create(_entity("test:entity:claim-subject"))
        object_entity = await entity_repository.create(_entity("test:entity:claim-object", "TOPIC"))

        claim = await claim_repository.create(
            Claim(
                id="test:claim:entity-valued",
                subject_entity_id=subject.id,
                predicate="PRODUCES",
                object_entity_id=object_entity.id,
                status=ClaimStatus.CONFIRMED,
            )
        )

        assert claim.id == "test:claim:entity-valued"

    run_with_client(body)


def test_list_for_entity_returns_claim_from_subject_side() -> None:
    async def body(client: Neo4jClient) -> None:
        entity_repository = EntityRepository(client)
        claim_repository = ClaimRepository(client)
        subject = await entity_repository.create(_entity("test:entity:subject-side"))
        object_entity = await entity_repository.create(_entity("test:entity:subject-side-object", "TOPIC"))
        claim = await claim_repository.create(
            Claim(
                id="test:claim:subject-side",
                subject_entity_id=subject.id,
                predicate="PRODUCES",
                object_entity_id=object_entity.id,
                status=ClaimStatus.CONFIRMED,
            )
        )

        claims = await claim_repository.list_for_entity(subject.id)

        assert claim.id in {item.id for item in claims}

    run_with_client(body)


def test_list_for_entity_returns_claim_from_object_side() -> None:
    async def body(client: Neo4jClient) -> None:
        entity_repository = EntityRepository(client)
        claim_repository = ClaimRepository(client)
        subject = await entity_repository.create(_entity("test:entity:object-side-subject"))
        object_entity = await entity_repository.create(_entity("test:entity:object-side", "TOPIC"))
        claim = await claim_repository.create(
            Claim(
                id="test:claim:object-side",
                subject_entity_id=subject.id,
                predicate="PRODUCES",
                object_entity_id=object_entity.id,
                status=ClaimStatus.CONFIRMED,
            )
        )

        claims = await claim_repository.list_for_entity(object_entity.id)

        assert claim.id in {item.id for item in claims}

    run_with_client(body)


def test_evidence_links_claim_to_knowledge_source() -> None:
    async def body(client: Neo4jClient) -> None:
        entity_repository = EntityRepository(client)
        source_repository = SourceRepository(client)
        claim_repository = ClaimRepository(client)
        subject = await entity_repository.create(_entity("test:entity:evidence-subject"))
        object_entity = await entity_repository.create(_entity("test:entity:evidence-object", "TOPIC"))
        source = await source_repository.create(
            KnowledgeSource(
                id="test:source:evidence",
                source_type=SourceType.SYSTEM,
                title="Evidence Source",
            )
        )
        claim = await claim_repository.create(
            Claim(
                id="test:claim:evidence",
                subject_entity_id=subject.id,
                predicate="PRODUCES",
                object_entity_id=object_entity.id,
                status=ClaimStatus.CONFIRMED,
            )
        )

        evidence = await claim_repository.add_evidence(
            Evidence(
                id="test:evidence:claim-source",
                claim_id=claim.id,
                source_id=source.id,
                excerpt="Evidence excerpt",
            )
        )

        async with client.session() as session:
            result = await session.run(
                """
                MATCH (:Claim {id: $claim_id})-[:SUPPORTED_BY]->(evidence:Evidence {id: $evidence_id})
                MATCH (evidence)-[:FROM_SOURCE]->(:KnowledgeSource {id: $source_id})
                RETURN count(evidence) AS count
                """,
                claim_id=claim.id,
                evidence_id=evidence.id,
                source_id=source.id,
            )
            record = await result.single()

        assert record is not None
        assert record["count"] == 1

    run_with_client(body)


def test_knowledge_gap_creation_and_list_open_works() -> None:
    async def body(client: Neo4jClient) -> None:
        entity_repository = EntityRepository(client)
        gap_repository = GapRepository(client)
        entity = await entity_repository.create(_entity("test:entity:gap", "BUSINESS_CONCEPT"))
        gap = await gap_repository.create(
            KnowledgeGap(
                id="test:gap:list-open",
                entity_id=entity.id,
                gap_type="MISSING_TEST_DETAIL",
                description="A test gap",
                priority=GapPriority.HIGH,
            )
        )

        gaps = await gap_repository.list_open()

        assert gap.id in {item.id for item in gaps}

    run_with_client(body)


def test_resolve_removes_gap_from_list_open() -> None:
    async def body(client: Neo4jClient) -> None:
        entity_repository = EntityRepository(client)
        gap_repository = GapRepository(client)
        entity = await entity_repository.create(_entity("test:entity:gap-resolve", "BUSINESS_CONCEPT"))
        gap = await gap_repository.create(
            KnowledgeGap(
                id="test:gap:resolve",
                entity_id=entity.id,
                gap_type="MISSING_TEST_DETAIL",
                description="A test gap",
                priority=GapPriority.HIGH,
            )
        )

        resolved = await gap_repository.resolve(gap.id)
        gaps = await gap_repository.list_open()

        assert resolved is not None
        assert resolved.status == "RESOLVED"
        assert gap.id not in {item.id for item in gaps}

    run_with_client(body)


def test_repeated_resolve_is_safe() -> None:
    async def body(client: Neo4jClient) -> None:
        entity_repository = EntityRepository(client)
        gap_repository = GapRepository(client)
        entity = await entity_repository.create(_entity("test:entity:gap-repeat-resolve", "BUSINESS_CONCEPT"))
        gap = await gap_repository.create(
            KnowledgeGap(
                id="test:gap:repeat-resolve",
                entity_id=entity.id,
                gap_type="MISSING_TEST_DETAIL",
                description="A test gap",
                priority=GapPriority.MEDIUM,
            )
        )

        first = await gap_repository.resolve(gap.id)
        second = await gap_repository.resolve(gap.id)

        assert first is not None
        assert second is not None
        assert second.status == "RESOLVED"
        assert second.resolved_at == first.resolved_at

    run_with_client(body)
