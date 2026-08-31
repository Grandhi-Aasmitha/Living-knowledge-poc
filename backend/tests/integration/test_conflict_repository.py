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
from app.domain.enums import ClaimStatus, SourceType
from app.domain.evidence import Evidence
from app.domain.source import KnowledgeSource
from app.repositories.claim_repository import ClaimRepository
from app.repositories.conflict_repository import ConflictRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.source_repository import SourceRepository

pytestmark = pytest.mark.integration
T = TypeVar("T")
NAMESPACE = "test-conflict-repository"


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
            return await test_body(client)
        finally:
            await cleanup(client)
            await client.close()

    return asyncio.run(runner())


async def cleanup(client: Neo4jClient) -> None:
    async with client.session() as session:
        await session.run("MATCH (conflict:KnowledgeConflict {namespace: $namespace}) DETACH DELETE conflict", namespace=NAMESPACE)
        await session.run("MATCH (evidence:Evidence) WHERE evidence.id STARTS WITH 'test:conflictrepo:' DETACH DELETE evidence")
        await session.run("MATCH (claim:Claim) WHERE claim.id STARTS WITH 'test:conflictrepo:' DETACH DELETE claim")
        await session.run("MATCH (source:KnowledgeSource) WHERE source.id STARTS WITH 'test:conflictrepo:' DETACH DELETE source")
        await session.run("MATCH (entity:Entity {namespace: $namespace}) DETACH DELETE entity", namespace=NAMESPACE)


def entity(entity_id: str, entity_type: str) -> Entity:
    return Entity(id=entity_id, entity_type=entity_type, canonical_name=entity_id.rsplit(":", 1)[-1], namespace=NAMESPACE)


async def fixture_entities(client: Neo4jClient) -> None:
    repository = EntityRepository(client)
    for item in [
        entity("test:conflictrepo:team:a", "TEAM"),
        entity("test:conflictrepo:team:b", "TEAM"),
        entity("test:conflictrepo:team:c", "TEAM"),
        entity("test:conflictrepo:service:x", "SERVICE"),
        entity("test:conflictrepo:system:a", "SYSTEM"),
        entity("test:conflictrepo:system:b", "SYSTEM"),
    ]:
        await repository.create(item)
    await SourceRepository(client).create(KnowledgeSource(id="test:conflictrepo:source", source_type=SourceType.SYSTEM, title="Conflict Repo Fixture"))


async def claim(client: Neo4jClient, claim_id: str, subject_id: str, predicate: str, object_id: str, status: ClaimStatus, with_evidence: bool = True) -> None:
    repository = ClaimRepository(client)
    await repository.create(
        Claim(
            id=claim_id,
            subject_entity_id=subject_id,
            predicate=predicate,
            object_entity_id=object_id,
            status=status,
            confidence=0.7,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    if with_evidence:
        await repository.add_evidence(Evidence(id=f"test:conflictrepo:evidence:{claim_id.rsplit(':', 1)[-1]}", claim_id=claim_id, source_id="test:conflictrepo:source"))


def test_multiple_owner_detection_requires_distinct_teams_evidence_and_counted_status() -> None:
    async def body(client: Neo4jClient) -> None:
        await fixture_entities(client)
        await claim(client, "test:conflictrepo:claim:a", "test:conflictrepo:team:a", "OWNS", "test:conflictrepo:service:x", ClaimStatus.CONFIRMED)
        await claim(client, "test:conflictrepo:claim:b", "test:conflictrepo:team:b", "OWNS", "test:conflictrepo:service:x", ClaimStatus.PROPOSED)
        await claim(client, "test:conflictrepo:claim:c", "test:conflictrepo:team:c", "OWNS", "test:conflictrepo:service:x", ClaimStatus.REJECTED)

        findings = await ConflictRepository(client).detect_multiple_owners(NAMESPACE)

        assert len(findings) == 1
        assert findings[0].claim_ids == ["test:conflictrepo:claim:a", "test:conflictrepo:claim:b"]

    run_with_client(body)


def test_claim_without_evidence_does_not_participate() -> None:
    async def body(client: Neo4jClient) -> None:
        await fixture_entities(client)
        await claim(client, "test:conflictrepo:claim:a", "test:conflictrepo:team:a", "OWNS", "test:conflictrepo:service:x", ClaimStatus.CONFIRMED)
        await claim(client, "test:conflictrepo:claim:b", "test:conflictrepo:team:b", "OWNS", "test:conflictrepo:service:x", ClaimStatus.CONFIRMED, with_evidence=False)

        assert await ConflictRepository(client).detect_multiple_owners(NAMESPACE) == []

    run_with_client(body)


def test_multiple_part_of_detection_requires_distinct_parents() -> None:
    async def body(client: Neo4jClient) -> None:
        await fixture_entities(client)
        await claim(client, "test:conflictrepo:claim:part-a", "test:conflictrepo:service:x", "PART_OF", "test:conflictrepo:system:a", ClaimStatus.CONFIRMED)
        await claim(client, "test:conflictrepo:claim:part-b", "test:conflictrepo:service:x", "PART_OF", "test:conflictrepo:system:b", ClaimStatus.PROPOSED)

        findings = await ConflictRepository(client).detect_multiple_part_of(NAMESPACE)

        assert len(findings) == 1
        assert findings[0].claim_ids == ["test:conflictrepo:claim:part-a", "test:conflictrepo:claim:part-b"]

    run_with_client(body)
