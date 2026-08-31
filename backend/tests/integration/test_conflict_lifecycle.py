import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

import pytest

from app.conflicts.rules import MULTIPLE_OWNERS_RULE_ID, MULTIPLE_PART_OF_RULE_ID
from app.conflicts.service import ConflictDetectionService, ConflictResolutionService, ConflictValidationError
from app.config import get_settings
from app.db.neo4j import Neo4jClient
from app.db.schema import ensure_schema
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.enums import ClaimStatus, ConflictResolutionType, ConflictStatus, SourceType
from app.domain.evidence import Evidence
from app.domain.source import KnowledgeSource
from app.repositories.claim_repository import ClaimRepository
from app.repositories.conflict_repository import ConflictRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.graph_repository import GraphRepository
from app.repositories.source_repository import SourceRepository
from app.conflicts.models import ConflictResolutionRequest

pytestmark = pytest.mark.integration
T = TypeVar("T")
NAMESPACE = "test-conflict-lifecycle"


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
        await session.run("MATCH (conflict:KnowledgeConflict {namespace: $namespace}) DETACH DELETE conflict", namespace=NAMESPACE)
        await session.run("MATCH (evidence:Evidence) WHERE evidence.id STARTS WITH 'test:conflict:' DETACH DELETE evidence")
        await session.run("MATCH (claim:Claim) WHERE claim.id STARTS WITH 'test:conflict:' DETACH DELETE claim")
        await session.run("MATCH (source:KnowledgeSource) WHERE source.id STARTS WITH 'test:conflict:' OR source.id STARTS WITH 'human:conflict:conflict:' DETACH DELETE source")
        await session.run("MATCH (entity:Entity {namespace: $namespace}) DETACH DELETE entity", namespace=NAMESPACE)


def entity(entity_id: str, entity_type: str, name: str | None = None) -> Entity:
    return Entity(
        id=entity_id,
        entity_type=entity_type,
        canonical_name=name or entity_id.rsplit(":", 1)[-1],
        namespace=NAMESPACE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


async def create_source(client: Neo4jClient) -> None:
    await SourceRepository(client).create(KnowledgeSource(id="test:conflict:source", source_type=SourceType.SYSTEM, title="Conflict Fixture"))


async def create_claim_with_evidence(
    client: Neo4jClient,
    claim_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
    status: ClaimStatus = ClaimStatus.CONFIRMED,
) -> Claim:
    claim_repository = ClaimRepository(client)
    claim = await claim_repository.create(
        Claim(
            id=claim_id,
            subject_entity_id=subject_id,
            predicate=predicate,
            object_entity_id=object_id,
            status=status,
            confidence=0.8,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await claim_repository.add_evidence(Evidence(id=f"test:conflict:evidence:{claim_id.rsplit(':', 1)[-1]}", claim_id=claim_id, source_id="test:conflict:source", excerpt=f"Evidence for {claim_id}"))
    return claim


async def setup_owner_conflict(client: Neo4jClient, second_status: ClaimStatus = ClaimStatus.PROPOSED) -> tuple[str, str]:
    entity_repository = EntityRepository(client)
    await create_source(client)
    await entity_repository.create(entity("test:conflict:team:alpha", "TEAM", "Team Alpha"))
    await entity_repository.create(entity("test:conflict:team:beta", "TEAM", "Team Beta"))
    await entity_repository.create(entity("test:conflict:team:gamma", "TEAM", "Team Gamma"))
    await entity_repository.create(entity("test:conflict:service:demo", "SERVICE", "Demo Service"))
    await create_claim_with_evidence(client, "test:conflict:claim:alpha-owns", "test:conflict:team:alpha", "OWNS", "test:conflict:service:demo", ClaimStatus.CONFIRMED)
    await create_claim_with_evidence(client, "test:conflict:claim:beta-owns", "test:conflict:team:beta", "OWNS", "test:conflict:service:demo", second_status)
    result = await ConflictDetectionService(ConflictRepository(client)).detect(NAMESPACE)
    assert result.conflicts_created == 1
    conflict = (await ConflictRepository(client).list_open(NAMESPACE))[0]
    return conflict.id, "test:conflict:claim:alpha-owns"


def test_multiple_owners_detection_idempotency_and_keep_claim_resolution() -> None:
    async def body(client: Neo4jClient) -> None:
        conflict_id, selected_claim_id = await setup_owner_conflict(client, ClaimStatus.PROPOSED)
        repository = ConflictRepository(client)

        second = await ConflictDetectionService(repository).detect(NAMESPACE)
        assert second.conflicts_created == 0
        assert second.conflicts_existing == 1

        detail = await repository.get(conflict_id)
        assert detail is not None
        assert detail.rule_id == MULTIPLE_OWNERS_RULE_ID
        assert {claim.claim_id for claim in detail.claims} == {"test:conflict:claim:alpha-owns", "test:conflict:claim:beta-owns"}
        assert all(claim.evidence_count == 1 for claim in detail.claims)

        resolution = await ConflictResolutionService(repository, ClaimRepository(client)).resolve(
            conflict_id,
            ConflictResolutionRequest(decision=ConflictResolutionType.KEEP_CLAIM, selected_claim_id=selected_claim_id, reason="Team Alpha is current."),
        )
        assert resolution.status == ConflictStatus.RESOLVED
        winner = await ClaimRepository(client).get("test:conflict:claim:alpha-owns")
        loser = await ClaimRepository(client).get("test:conflict:claim:beta-owns")
        assert winner is not None and winner.status == ClaimStatus.CONFIRMED
        assert loser is not None and loser.status == ClaimStatus.REJECTED
        provenance = await GraphRepository(client).get_claim_provenance("test:conflict:claim:alpha-owns")
        assert provenance is not None
        assert any(evidence.source_type == "HUMAN" and evidence.excerpt == "Team Alpha is current." for evidence in provenance.evidence)

    run_with_client(body)


def test_confirmed_loser_is_superseded_and_history_remains() -> None:
    async def body(client: Neo4jClient) -> None:
        conflict_id, selected_claim_id = await setup_owner_conflict(client, ClaimStatus.CONFIRMED)
        await ConflictResolutionService(ConflictRepository(client), ClaimRepository(client)).resolve(
            conflict_id,
            ConflictResolutionRequest(decision=ConflictResolutionType.KEEP_CLAIM, selected_claim_id=selected_claim_id, reason="Team Alpha supersedes Team Beta."),
        )
        loser = await ClaimRepository(client).get("test:conflict:claim:beta-owns")
        assert loser is not None and loser.status == ClaimStatus.SUPERSEDED
        async with client.session() as session:
            result = await session.run(
                """
                MATCH (:Claim {id: 'test:conflict:claim:beta-owns'})-[:SUPERSEDED_BY]->(:Claim {id: 'test:conflict:claim:alpha-owns'})
                RETURN count(*) AS count
                """
            )
            record = await result.single()
            evidence_result = await session.run("MATCH (:Claim {id: 'test:conflict:claim:beta-owns'})-[:SUPPORTED_BY]->(:Evidence) RETURN count(*) AS count")
            evidence_record = await evidence_result.single()
        assert record is not None and record["count"] == 1
        assert evidence_record is not None and evidence_record["count"] == 1

    run_with_client(body)


def test_both_valid_dismissal_suppresses_same_signature() -> None:
    async def body(client: Neo4jClient) -> None:
        conflict_id, _ = await setup_owner_conflict(client)
        service = ConflictResolutionService(ConflictRepository(client), ClaimRepository(client))
        await service.resolve(conflict_id, ConflictResolutionRequest(decision=ConflictResolutionType.BOTH_VALID, reason="Joint ownership during migration."))
        conflict = await ConflictRepository(client).get_conflict(conflict_id)
        assert conflict is not None
        assert conflict.status == ConflictStatus.DISMISSED
        assert conflict.resolution_type == ConflictResolutionType.BOTH_VALID

        rerun = await ConflictDetectionService(ConflictRepository(client)).detect(NAMESPACE)
        assert rerun.conflicts_created == 0
        assert rerun.conflicts_existing == 1
        assert rerun.open_conflicts == 0

    run_with_client(body)


def test_corrected_resolution_creates_confirmed_claim_and_rejects_losers() -> None:
    async def body(client: Neo4jClient) -> None:
        conflict_id, _ = await setup_owner_conflict(client)
        resolution = await ConflictResolutionService(ConflictRepository(client), ClaimRepository(client)).resolve(
            conflict_id,
            ConflictResolutionRequest(
                decision=ConflictResolutionType.CORRECTED,
                reason="Team Gamma is the current owner.",
                corrected_subject_entity_id="test:conflict:team:gamma",
                corrected_predicate="OWNS",
                corrected_object_entity_id="test:conflict:service:demo",
            ),
        )
        assert resolution.corrected_claim_id is not None
        corrected = await ClaimRepository(client).get(resolution.corrected_claim_id)
        assert corrected is not None
        assert corrected.status == ClaimStatus.CONFIRMED
        assert corrected.confidence == 1.0
        alpha = await ClaimRepository(client).get("test:conflict:claim:alpha-owns")
        beta = await ClaimRepository(client).get("test:conflict:claim:beta-owns")
        assert alpha is not None and alpha.status == ClaimStatus.SUPERSEDED
        assert beta is not None and beta.status == ClaimStatus.REJECTED
        provenance = await GraphRepository(client).get_claim_provenance(corrected.id)
        assert provenance is not None
        assert any(evidence.source_type == "HUMAN" and evidence.excerpt == "Team Gamma is the current owner." for evidence in provenance.evidence)

    run_with_client(body)


def test_invalid_correction_does_not_mutate_graph() -> None:
    async def body(client: Neo4jClient) -> None:
        conflict_id, _ = await setup_owner_conflict(client)
        with pytest.raises(ConflictValidationError):
            await ConflictResolutionService(ConflictRepository(client), ClaimRepository(client)).resolve(
                conflict_id,
                ConflictResolutionRequest(
                    decision=ConflictResolutionType.CORRECTED,
                    reason="Invalid subject.",
                    corrected_subject_entity_id="test:conflict:service:demo",
                    corrected_predicate="OWNS",
                    corrected_object_entity_id="test:conflict:service:demo",
                ),
            )
        alpha = await ClaimRepository(client).get("test:conflict:claim:alpha-owns")
        beta = await ClaimRepository(client).get("test:conflict:claim:beta-owns")
        conflict = await ConflictRepository(client).get_conflict(conflict_id)
        assert alpha is not None and alpha.status == ClaimStatus.CONFIRMED
        assert beta is not None and beta.status == ClaimStatus.PROPOSED
        assert conflict is not None and conflict.status == ConflictStatus.OPEN

    run_with_client(body)


def test_multiple_part_of_detection_and_auto_clear() -> None:
    async def body(client: Neo4jClient) -> None:
        entity_repository = EntityRepository(client)
        await create_source(client)
        await entity_repository.create(entity("test:conflict:service:part", "SERVICE", "Part Service"))
        await entity_repository.create(entity("test:conflict:system:a", "SYSTEM", "System A"))
        await entity_repository.create(entity("test:conflict:system:b", "SYSTEM", "System B"))
        await create_claim_with_evidence(client, "test:conflict:claim:part-a", "test:conflict:service:part", "PART_OF", "test:conflict:system:a")
        await create_claim_with_evidence(client, "test:conflict:claim:part-b", "test:conflict:service:part", "PART_OF", "test:conflict:system:b")
        repository = ConflictRepository(client)
        result = await ConflictDetectionService(repository).detect(NAMESPACE)
        assert result.conflicts_created == 1
        conflict = (await repository.list_open(NAMESPACE))[0]
        assert conflict.rule_id == MULTIPLE_PART_OF_RULE_ID

        async with client.session() as session:
            await session.run("MATCH (claim:Claim {id: 'test:conflict:claim:part-b'}) SET claim.status = 'REJECTED'")
        cleared = await ConflictDetectionService(repository).detect(NAMESPACE)
        assert cleared.conflicts_auto_cleared == 1
        assert cleared.open_conflicts == 0

    run_with_client(body)


def test_namespace_isolation() -> None:
    async def body(client: Neo4jClient) -> None:
        entity_repository = EntityRepository(client)
        await create_source(client)
        await entity_repository.create(entity("test:conflict:team:a", "TEAM", "Team A"))
        await entity_repository.create(entity("test:conflict:service:isolated", "SERVICE", "Isolated Service"))
        await create_claim_with_evidence(client, "test:conflict:claim:isolated-a", "test:conflict:team:a", "OWNS", "test:conflict:service:isolated")
        other = Entity(id="test:conflict:team:other", entity_type="TEAM", canonical_name="Other Team", namespace="other-conflict-space")
        await entity_repository.create(other)
        await ClaimRepository(client).create(
            Claim(id="test:conflict:claim:other-space", subject_entity_id="test:conflict:team:other", predicate="OWNS", object_entity_id="test:conflict:service:isolated", status=ClaimStatus.CONFIRMED)
        )
        await ClaimRepository(client).add_evidence(Evidence(id="test:conflict:evidence:other-space", claim_id="test:conflict:claim:other-space", source_id="test:conflict:source"))

        result = await ConflictDetectionService(ConflictRepository(client)).detect(NAMESPACE)
        assert result.findings_detected == 0
        assert result.conflicts_created == 0

    run_with_client(body)
