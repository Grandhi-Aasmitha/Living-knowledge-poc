import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

import pytest

from app.assistant.models import QueryDirection
from app.config import get_settings
from app.db.neo4j import Neo4jClient
from app.db.schema import ensure_schema
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.enums import ClaimStatus, ConflictStatus, GapPriority, GapStatus, SourceType
from app.domain.evidence import Evidence
from app.domain.gap import KnowledgeGap
from app.domain.source import KnowledgeSource
from app.conflicts.models import KnowledgeConflict
from app.repositories.claim_repository import ClaimRepository
from app.repositories.conflict_repository import ConflictRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.gap_repository import GapRepository
from app.repositories.knowledge_query_repository import KnowledgeQueryRepository
from app.repositories.source_repository import SourceRepository

pytestmark = pytest.mark.integration
T = TypeVar("T")
NAMESPACE = "test-assistant-repo"


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
        await session.run("MATCH (gap:KnowledgeGap) WHERE gap.id STARTS WITH 'test:assistantrepo:' DETACH DELETE gap")
        await session.run("MATCH (evidence:Evidence) WHERE evidence.id STARTS WITH 'test:assistantrepo:' DETACH DELETE evidence")
        await session.run("MATCH (claim:Claim) WHERE claim.id STARTS WITH 'test:assistantrepo:' DETACH DELETE claim")
        await session.run("MATCH (source:KnowledgeSource) WHERE source.id STARTS WITH 'test:assistantrepo:' DETACH DELETE source")
        await session.run("MATCH (entity:Entity {namespace: $namespace}) DETACH DELETE entity", namespace=NAMESPACE)
        await session.run("MATCH (entity:Entity {namespace: 'other-assistant-repo'}) DETACH DELETE entity")


def entity(entity_id: str, name: str, entity_type: str = "SERVICE", aliases: list[str] | None = None, namespace: str = NAMESPACE) -> Entity:
    return Entity(id=entity_id, entity_type=entity_type, canonical_name=name, namespace=namespace, aliases=aliases or [])


async def create_base(client: Neo4jClient) -> None:
    entities = [
        entity("test:assistantrepo:team", "Eval Team", "TEAM", ["Team Alias"]),
        entity("test:assistantrepo:service", "Eval Service", "SERVICE", ["Service Alias"]),
        entity("test:assistantrepo:topic", "Eval Topic", "TOPIC"),
        entity("test:assistantrepo:consumer", "Eval Consumer", "SERVICE"),
        entity("test:assistantrepo:database", "Eval Database", "DATABASE"),
        entity("test:assistantrepo:ambiguous-a", "Shared Name", "SERVICE"),
        entity("test:assistantrepo:ambiguous-b", "Shared Name", "SYSTEM"),
        entity("test:assistantrepo:other", "Other Service", "SERVICE", namespace="other-assistant-repo"),
    ]
    entity_repository = EntityRepository(client)
    for item in entities:
        await entity_repository.create(item)
    await SourceRepository(client).create(KnowledgeSource(id="test:assistantrepo:source", source_type=SourceType.SYSTEM, title="Assistant Repo Fixture"))


async def create_claim(client: Neo4jClient, claim_id: str, subject: str, predicate: str, object_id: str | None, status: ClaimStatus, with_evidence: bool = True, object_value: str | None = None) -> None:
    repository = ClaimRepository(client)
    await repository.create(
        Claim(
            id=claim_id,
            subject_entity_id=subject,
            predicate=predicate,
            object_entity_id=object_id,
            object_value=object_value,
            status=status,
            confidence=0.9,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    if with_evidence:
        await repository.add_evidence(Evidence(id=f"test:assistantrepo:evidence:{claim_id.rsplit(':', 1)[-1]}", claim_id=claim_id, source_id="test:assistantrepo:source", excerpt=f"Evidence for {claim_id}"))


def test_resolves_exact_alias_and_ambiguity() -> None:
    async def body(client: Neo4jClient) -> None:
        await create_base(client)
        repository = KnowledgeQueryRepository(client)

        exact, alias, ambiguous, missing = await repository.resolve_entities(["Eval Service", "Team Alias", "Shared Name", "Missing"], NAMESPACE)

        assert [match.id for match in exact.matches] == ["test:assistantrepo:service"]
        assert [match.id for match in alias.matches] == ["test:assistantrepo:team"]
        assert {match.id for match in ambiguous.matches} == {"test:assistantrepo:ambiguous-a", "test:assistantrepo:ambiguous-b"}
        assert missing.matches == []

    run_with_client(body)


def test_retrieves_source_backed_current_claims_with_filters_and_literal_values() -> None:
    async def body(client: Neo4jClient) -> None:
        await create_base(client)
        await create_claim(client, "test:assistantrepo:claim:owns", "test:assistantrepo:team", "OWNS", "test:assistantrepo:service", ClaimStatus.CONFIRMED)
        await create_claim(client, "test:assistantrepo:claim:produces", "test:assistantrepo:service", "PRODUCES", "test:assistantrepo:topic", ClaimStatus.PROPOSED)
        await create_claim(client, "test:assistantrepo:claim:literal", "test:assistantrepo:service", "PURPOSE", None, ClaimStatus.CONFIRMED, object_value="Runs evaluation")
        await create_claim(client, "test:assistantrepo:claim:rejected", "test:assistantrepo:service", "CALLS", "test:assistantrepo:database", ClaimStatus.REJECTED)
        await create_claim(client, "test:assistantrepo:claim:unsupported", "test:assistantrepo:service", "CONSUMES", "test:assistantrepo:topic", ClaimStatus.CONFIRMED, with_evidence=False)

        repository = KnowledgeQueryRepository(client)
        incoming = await repository.get_claim_context(["test:assistantrepo:service"], ["OWNS"], QueryDirection.INCOMING, NAMESPACE, 25, 2)
        outgoing = await repository.get_claim_context(["test:assistantrepo:service"], [], QueryDirection.OUTGOING, NAMESPACE, 25, 2)

        assert [claim.claim_id for claim in incoming] == ["test:assistantrepo:claim:owns"]
        outgoing_ids = {claim.claim_id for claim in outgoing}
        assert "test:assistantrepo:claim:produces" in outgoing_ids
        assert "test:assistantrepo:claim:literal" in outgoing_ids
        assert "test:assistantrepo:claim:rejected" not in outgoing_ids
        assert "test:assistantrepo:claim:unsupported" not in outgoing_ids
        literal = next(claim for claim in outgoing if claim.claim_id == "test:assistantrepo:claim:literal")
        assert literal.object_value == "Runs evaluation"
        assert literal.evidence[0].source_title == "Assistant Repo Fixture"

    run_with_client(body)


def test_namespace_isolation_and_open_gap_conflict_context() -> None:
    async def body(client: Neo4jClient) -> None:
        await create_base(client)
        await create_claim(client, "test:assistantrepo:claim:owns", "test:assistantrepo:team", "OWNS", "test:assistantrepo:service", ClaimStatus.CONFIRMED)
        await GapRepository(client).create(
            KnowledgeGap(
                id="test:assistantrepo:gap:one",
                entity_id="test:assistantrepo:service",
                gap_type="MISSING_OWNER",
                description="Synthetic gap",
                priority=GapPriority.MEDIUM,
                status=GapStatus.OPEN,
            )
        )
        conflict = KnowledgeConflict(id="test:assistantrepo:conflict:one", rule_id="multiple-owners-v1", namespace=NAMESPACE, description="Synthetic conflict", status=ConflictStatus.OPEN)
        await ConflictRepository(client).create(conflict, ["test:assistantrepo:claim:owns"])

        repository = KnowledgeQueryRepository(client)
        other_matches = await repository.resolve_entities(["Other Service"], NAMESPACE)
        gaps = await repository.get_open_gaps(["test:assistantrepo:service"])
        conflicts = await repository.get_open_conflicts(["test:assistantrepo:claim:owns"])

        assert other_matches[0].matches == []
        assert [gap.id for gap in gaps] == ["test:assistantrepo:gap:one"]
        assert [item.id for item in conflicts] == ["test:assistantrepo:conflict:one"]

    run_with_client(body)


def test_service_evidence_search_is_bounded_to_current_namespace_claims() -> None:
    async def body(client: Neo4jClient) -> None:
        await create_base(client)
        await create_claim(client, "test:assistantrepo:claim:shipment", "test:assistantrepo:service", "WRITES_TO", "test:assistantrepo:database", ClaimStatus.PROPOSED)
        await create_claim(client, "test:assistantrepo:claim:rejected", "test:assistantrepo:service", "CALLS", "test:assistantrepo:database", ClaimStatus.REJECTED)
        await create_claim(client, "test:assistantrepo:claim:stale", "test:assistantrepo:service", "USES", "test:assistantrepo:database", ClaimStatus.CONFIRMED)
        await create_claim(client, "test:assistantrepo:claim:other", "test:assistantrepo:other", "PURPOSE", None, ClaimStatus.PROPOSED, object_value="Shipment details")
        async with client.session() as session:
            await session.run(
                "MATCH (e:Evidence) WHERE e.id STARTS WITH 'test:assistantrepo:evidence:' SET e.excerpt = 'Stores shipment details.'"
            )
            await session.run(
                "MATCH (e:Evidence {id: 'test:assistantrepo:evidence:stale'}) SET e.is_current = false"
            )

        repository = KnowledgeQueryRepository(client)
        ids = await repository.search_service_claim_ids(["shipment"], NAMESPACE, 25)
        claims = await repository.get_claim_context([], [], QueryDirection.BOTH, NAMESPACE, 25, 2, ids)

        assert ids == ["test:assistantrepo:claim:shipment"]
        assert [claim.claim_id for claim in claims] == ids

    run_with_client(body)
