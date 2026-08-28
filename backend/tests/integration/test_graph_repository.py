import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

import pytest

from app.config import get_settings
from app.db.neo4j import Neo4jClient
from app.db.schema import ensure_schema
from app.documents.models import SourceChunk, SourceDocument, SourceVersion
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.enums import ClaimStatus, SourceType
from app.domain.evidence import Evidence
from app.domain.source import KnowledgeSource
from app.repositories.claim_repository import ClaimRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.graph_repository import GraphRepository
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
        await session.run("MATCH (evidence:Evidence) WHERE evidence.id STARTS WITH 'test:graph:' DETACH DELETE evidence")
        await session.run("MATCH (claim:Claim) WHERE claim.id STARTS WITH 'test:graph:' DETACH DELETE claim")
        await session.run("MATCH (chunk:SourceChunk) WHERE chunk.id STARTS WITH 'test:graph:' DETACH DELETE chunk")
        await session.run("MATCH (version:SourceVersion) WHERE version.id STARTS WITH 'test:graph:' DETACH DELETE version")
        await session.run("MATCH (document:SourceDocument) WHERE document.id STARTS WITH 'test:graph:' DETACH DELETE document")
        await session.run("MATCH (source:KnowledgeSource) WHERE source.id STARTS WITH 'test:graph:' DETACH DELETE source")
        await session.run("MATCH (entity:Entity) WHERE entity.id STARTS WITH 'test:graph:' DETACH DELETE entity")


def _entity(entity_id: str, namespace: str = "test-graph", entity_type: str = "SERVICE") -> Entity:
    return Entity(
        id=entity_id,
        entity_type=entity_type,
        canonical_name=entity_id.rsplit(":", 1)[-1],
        namespace=namespace,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


async def _create_entity_claim(
    client: Neo4jClient,
    claim_id: str,
    subject_id: str,
    object_id: str,
    predicate: str,
    status: ClaimStatus,
    namespace: str = "test-graph",
) -> Claim:
    entity_repository = EntityRepository(client)
    claim_repository = ClaimRepository(client)
    await entity_repository.create(_entity(subject_id, namespace=namespace))
    await entity_repository.create(_entity(object_id, namespace=namespace, entity_type="TOPIC"))
    return await claim_repository.create(
        Claim(
            id=claim_id,
            subject_entity_id=subject_id,
            predicate=predicate,
            object_entity_id=object_id,
            status=status,
            confidence=0.75,
        )
    )


def test_default_graph_includes_confirmed_and_proposed_excludes_rejected_and_counts_evidence() -> None:
    async def body(client: Neo4jClient) -> None:
        source_repository = SourceRepository(client)
        claim_repository = ClaimRepository(client)
        graph_repository = GraphRepository(client)
        await source_repository.create(KnowledgeSource(id="test:graph:source:default", source_type=SourceType.SYSTEM, title="Synthetic Source"))
        await _create_entity_claim(client, "test:graph:claim:confirmed", "test:graph:entity:a", "test:graph:entity:b", "PRODUCES", ClaimStatus.CONFIRMED)
        await _create_entity_claim(client, "test:graph:claim:proposed", "test:graph:entity:a", "test:graph:entity:c", "CONSUMES", ClaimStatus.PROPOSED)
        await _create_entity_claim(client, "test:graph:claim:rejected", "test:graph:entity:a", "test:graph:entity:d", "OWNS", ClaimStatus.REJECTED)
        await claim_repository.add_evidence(Evidence(id="test:graph:evidence:one", claim_id="test:graph:claim:confirmed", source_id="test:graph:source:default"))
        await claim_repository.add_evidence(Evidence(id="test:graph:evidence:two", claim_id="test:graph:claim:confirmed", source_id="test:graph:source:default"))

        graph = await graph_repository.get_entity_graph(namespace="test-graph", claim_statuses=["CONFIRMED", "PROPOSED"])

        assert {edge.id for edge in graph.edges} == {"test:graph:claim:confirmed", "test:graph:claim:proposed"}
        confirmed = next(edge for edge in graph.edges if edge.id == "test:graph:claim:confirmed")
        assert confirmed.source == "test:graph:entity:a"
        assert confirmed.target == "test:graph:entity:b"
        assert confirmed.predicate == "PRODUCES"
        assert confirmed.evidence_count == 2
        assert len(graph.nodes) == len({node.id for node in graph.nodes})

    run_with_client(body)


def test_focus_entity_returns_one_hop_neighborhood_only() -> None:
    async def body(client: Neo4jClient) -> None:
        graph_repository = GraphRepository(client)
        await _create_entity_claim(client, "test:graph:claim:ab", "test:graph:entity:focus-a", "test:graph:entity:focus-b", "CALLS", ClaimStatus.CONFIRMED)
        await _create_entity_claim(client, "test:graph:claim:bc", "test:graph:entity:focus-b", "test:graph:entity:focus-c", "CALLS", ClaimStatus.CONFIRMED)
        await _create_entity_claim(client, "test:graph:claim:cd", "test:graph:entity:focus-c", "test:graph:entity:focus-d", "CALLS", ClaimStatus.CONFIRMED)

        graph = await graph_repository.get_entity_graph(
            namespace="test-graph",
            claim_statuses=["CONFIRMED", "PROPOSED"],
            focus_entity_id="test:graph:entity:focus-b",
        )

        assert {node.id for node in graph.nodes} == {"test:graph:entity:focus-a", "test:graph:entity:focus-b", "test:graph:entity:focus-c"}
        assert {edge.id for edge in graph.edges} == {"test:graph:claim:ab", "test:graph:claim:bc"}

    run_with_client(body)


def test_namespace_isolation() -> None:
    async def body(client: Neo4jClient) -> None:
        graph_repository = GraphRepository(client)
        await _create_entity_claim(client, "test:graph:claim:space-a", "test:graph:entity:space-a-subject", "test:graph:entity:space-a-object", "OWNS", ClaimStatus.CONFIRMED, namespace="test-space-a")
        await _create_entity_claim(client, "test:graph:claim:space-b", "test:graph:entity:space-b-subject", "test:graph:entity:space-b-object", "OWNS", ClaimStatus.CONFIRMED, namespace="test-space-b")

        graph = await graph_repository.get_entity_graph(namespace="test-space-a", claim_statuses=["CONFIRMED", "PROPOSED"])

        assert {edge.id for edge in graph.edges} == {"test:graph:claim:space-a"}
        assert {node.namespace for node in graph.nodes} == {"test-space-a"}

    run_with_client(body)


def test_document_provenance_resolves_chunk_document_and_source_fields() -> None:
    async def body(client: Neo4jClient) -> None:
        source_repository = SourceRepository(client)
        document_repository = DocumentRepository(client)
        claim_repository = ClaimRepository(client)
        graph_repository = GraphRepository(client)
        await _create_entity_claim(client, "test:graph:claim:document", "test:graph:entity:doc-subject", "test:graph:entity:doc-object", "CONSUMES", ClaimStatus.PROPOSED)
        await source_repository.create(KnowledgeSource(id="test:graph:source:document", source_type=SourceType.FILE_UPLOAD, title="Synthetic File"))
        await document_repository.create_document(SourceDocument(id="test:graph:document:one", source_id="test:graph:source:document", external_id="synthetic.md", title="Synthetic Architecture", filename="synthetic.md", latest_version=1, current_content_hash="hash"))
        await document_repository.create_version(SourceVersion(id="test:graph:version:one", document_id="test:graph:document:one", version_number=1, content_hash="hash", storage_key="private/storage/key"))
        await document_repository.create_chunks([SourceChunk(id="test:graph:chunk:one", version_id="test:graph:version:one", sequence=0, content="Synthetic chunk", locator="section-1", content_hash="chunk-hash")])
        await claim_repository.add_evidence(Evidence(id="test:graph:evidence:document", claim_id="test:graph:claim:document", source_id="test:graph:source:document", source_chunk_id="test:graph:chunk:one", excerpt="Document excerpt", locator="p1"))

        provenance = await graph_repository.get_claim_provenance("test:graph:claim:document")

        assert provenance is not None
        assert provenance.object_name == "doc-object"
        assert len(provenance.evidence) == 1
        summary = provenance.evidence[0]
        assert summary.source_type == "FILE_UPLOAD"
        assert summary.source_title == "Synthetic File"
        assert summary.excerpt == "Document excerpt"
        assert summary.locator == "p1"
        assert summary.document_title == "Synthetic Architecture"
        assert summary.document_version == 1
        assert summary.chunk_locator == "section-1"

    run_with_client(body)


def test_human_provenance_without_chunk_returns_null_document_fields() -> None:
    async def body(client: Neo4jClient) -> None:
        source_repository = SourceRepository(client)
        claim_repository = ClaimRepository(client)
        graph_repository = GraphRepository(client)
        await _create_entity_claim(client, "test:graph:claim:human", "test:graph:entity:human-subject", "test:graph:entity:human-object", "OWNS", ClaimStatus.CONFIRMED)
        await source_repository.create(KnowledgeSource(id="test:graph:source:human", source_type=SourceType.HUMAN, title="Engineer Answer"))
        await claim_repository.add_evidence(Evidence(id="test:graph:evidence:human", claim_id="test:graph:claim:human", source_id="test:graph:source:human", excerpt="Human excerpt"))

        provenance = await graph_repository.get_claim_provenance("test:graph:claim:human")

        assert provenance is not None
        assert provenance.evidence[0].source_type == "HUMAN"
        assert provenance.evidence[0].document_title is None
        assert provenance.evidence[0].document_version is None
        assert provenance.evidence[0].chunk_locator is None

    run_with_client(body)


def test_literal_claim_is_not_projected_as_graph_edge_but_has_provenance() -> None:
    async def body(client: Neo4jClient) -> None:
        entity_repository = EntityRepository(client)
        claim_repository = ClaimRepository(client)
        graph_repository = GraphRepository(client)
        await entity_repository.create(_entity("test:graph:entity:literal"))
        await claim_repository.create(
            Claim(
                id="test:graph:claim:literal",
                subject_entity_id="test:graph:entity:literal",
                predicate="PURPOSE",
                object_value="Coordinates synthetic tests",
                status=ClaimStatus.CONFIRMED,
            )
        )

        graph = await graph_repository.get_entity_graph(namespace="test-graph", claim_statuses=["CONFIRMED", "PROPOSED"])
        provenance = await graph_repository.get_claim_provenance("test:graph:claim:literal")

        assert "test:graph:claim:literal" not in {edge.id for edge in graph.edges}
        assert provenance is not None
        assert provenance.object_entity_id is None
        assert provenance.object_value == "Coordinates synthetic tests"

    run_with_client(body)
