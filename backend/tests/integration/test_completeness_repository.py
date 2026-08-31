import asyncio
from collections.abc import Awaitable, Callable
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
from app.repositories.completeness_repository import CompletenessRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.source_repository import SourceRepository

pytestmark = pytest.mark.integration
T = TypeVar("T")
NAMESPACE = "phase6-repo-test"


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
        await session.run("MATCH (evidence:Evidence) WHERE evidence.id STARTS WITH 'phase6:repo:' DETACH DELETE evidence")
        await session.run("MATCH (claim:Claim) WHERE claim.id STARTS WITH 'phase6:repo:' DETACH DELETE claim")
        await session.run("MATCH (source:KnowledgeSource) WHERE source.id STARTS WITH 'phase6:repo:' DETACH DELETE source")
        await session.run("MATCH (entity:Entity {namespace: $namespace}) DETACH DELETE entity", namespace=NAMESPACE)


async def create_entity(client: Neo4jClient, entity_id: str, entity_type: str, name: str | None = None, status: str = "ACTIVE") -> Entity:
    return await EntityRepository(client).create(
        Entity(
            id=entity_id,
            entity_type=entity_type,
            canonical_name=name or entity_id,
            namespace=NAMESPACE,
            status=status,
        )
    )


async def create_claim(
    client: Neo4jClient,
    claim_id: str,
    subject: Entity,
    predicate: str,
    object_entity: Entity,
    status: ClaimStatus = ClaimStatus.CONFIRMED,
    with_evidence: bool = True,
) -> Claim:
    source_repository = SourceRepository(client)
    claim_repository = ClaimRepository(client)
    source = await source_repository.create(
        KnowledgeSource(
            id=f"phase6:repo:source:{claim_id}",
            source_type=SourceType.SYSTEM,
            title="Synthetic completeness test source",
        )
    )
    claim = await claim_repository.create(
        Claim(
            id=claim_id,
            subject_entity_id=subject.id,
            predicate=predicate,
            object_entity_id=object_entity.id,
            status=status,
        )
    )
    if with_evidence:
        await claim_repository.add_evidence(
            Evidence(
                id=f"phase6:repo:evidence:{claim_id}",
                claim_id=claim.id,
                source_id=source.id,
                excerpt="Synthetic evidence.",
            )
        )
    return claim


def test_find_missing_consumer() -> None:
    async def body(client: Neo4jClient) -> None:
        topic = await create_entity(client, "phase6:repo:topic:dispatch", "TOPIC", "Dispatch Topic")
        producer = await create_entity(client, "phase6:repo:service:producer", "SERVICE", "Producer Service")
        await create_claim(client, "phase6:repo:claim:producer", producer, "PRODUCES", topic)

        findings = await CompletenessRepository(client).find_missing_consumers(NAMESPACE)

        assert [finding.entity_id for finding in findings] == [topic.id]
        assert findings[0].description == "No consumer is currently known for Dispatch Topic."

    run_with_client(body)


def test_find_missing_producer() -> None:
    async def body(client: Neo4jClient) -> None:
        topic = await create_entity(client, "phase6:repo:topic:inbound", "BUSINESS_CONCEPT", "Inbound Concept")
        consumer = await create_entity(client, "phase6:repo:service:consumer", "SYSTEM", "Consumer System")
        await create_claim(client, "phase6:repo:claim:consumer", consumer, "CONSUMES", topic)

        findings = await CompletenessRepository(client).find_missing_producers(NAMESPACE)

        assert [finding.entity_id for finding in findings] == [topic.id]
        assert findings[0].description == "No producer is currently known for Inbound Concept."

    run_with_client(body)


def test_find_missing_owner() -> None:
    async def body(client: Neo4jClient) -> None:
        service = await create_entity(client, "phase6:repo:service:ownerless", "SERVICE", "Ownerless Service")

        findings = await CompletenessRepository(client).find_missing_owners(NAMESPACE)

        assert [finding.entity_id for finding in findings] == [service.id]
        assert findings[0].description == "No owning team is currently known for Ownerless Service."

    run_with_client(body)


def test_proposed_claim_counts_and_claim_without_evidence_does_not_count() -> None:
    async def body(client: Neo4jClient) -> None:
        topic_with_proposed = await create_entity(client, "phase6:repo:topic:proposed", "FLOW", "Proposed Flow")
        topic_without_evidence = await create_entity(client, "phase6:repo:topic:no-evidence", "FLOW", "No Evidence Flow")
        producer = await create_entity(client, "phase6:repo:service:producer", "SERVICE", "Producer Service")
        await create_claim(client, "phase6:repo:claim:proposed", producer, "PRODUCES", topic_with_proposed, ClaimStatus.PROPOSED)
        await create_claim(client, "phase6:repo:claim:no-evidence", producer, "PRODUCES", topic_without_evidence, ClaimStatus.CONFIRMED, with_evidence=False)

        findings = await CompletenessRepository(client).find_missing_consumers(NAMESPACE)

        assert {finding.entity_id for finding in findings} == {topic_with_proposed.id}

    run_with_client(body)


@pytest.mark.parametrize("status", [ClaimStatus.REJECTED, ClaimStatus.DISPUTED, ClaimStatus.SUPERSEDED, ClaimStatus.RETIRED])
def test_non_counted_statuses_do_not_satisfy_knowledge_criteria(status: ClaimStatus) -> None:
    async def body(client: Neo4jClient) -> None:
        topic = await create_entity(client, f"phase6:repo:topic:{status.value.casefold()}", "TOPIC", f"{status.value} Topic")
        producer = await create_entity(client, f"phase6:repo:service:{status.value.casefold()}", "SERVICE", f"{status.value} Service")
        await create_claim(client, f"phase6:repo:claim:{status.value.casefold()}", producer, "PRODUCES", topic, status)

        findings = await CompletenessRepository(client).find_missing_consumers(NAMESPACE)

        assert topic.id not in {finding.entity_id for finding in findings}

    run_with_client(body)


def test_active_entity_and_namespace_isolation() -> None:
    async def body(client: Neo4jClient) -> None:
        active_topic = await create_entity(client, "phase6:repo:topic:active", "TOPIC", "Active Topic")
        retired_topic = await create_entity(client, "phase6:repo:topic:retired", "TOPIC", "Retired Topic", status="RETIRED")
        producer = await create_entity(client, "phase6:repo:service:active-producer", "SERVICE", "Active Producer")
        await create_claim(client, "phase6:repo:claim:active", producer, "PRODUCES", active_topic)
        await create_claim(client, "phase6:repo:claim:retired", producer, "PRODUCES", retired_topic)

        other_namespace_topic = await EntityRepository(client).create(
            Entity(id="phase6:repo:topic:other", entity_type="TOPIC", canonical_name="Other Topic", namespace="phase6-other")
        )
        other_producer = await EntityRepository(client).create(
            Entity(id="phase6:repo:service:other", entity_type="SERVICE", canonical_name="Other Producer", namespace="phase6-other")
        )
        await create_claim(client, "phase6:repo:claim:other", other_producer, "PRODUCES", other_namespace_topic)

        findings = await CompletenessRepository(client).find_missing_consumers(NAMESPACE)

        assert {finding.entity_id for finding in findings} == {active_topic.id}

    run_with_client(body)
