import asyncio
from collections import deque
from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel

from app.config import get_settings
from app.db.neo4j import Neo4jClient
from app.db.schema import ensure_schema
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.enums import ClaimStatus, EntityStatus, SourceType
from app.domain.evidence import Evidence
from app.domain.identifiers import normalize_filename, stable_source_document_id
from app.domain.source import KnowledgeSource
from app.repositories.claim_repository import ClaimRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.source_repository import SourceRepository
from app.services.file_ingestion_service import FILE_UPLOAD_SOURCE_ID, FileIngestionService

pytestmark = pytest.mark.integration
T = TypeVar("T", bound=BaseModel)


def run(coro):
    return asyncio.run(coro)


class FakeStructuredAIClient:
    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = deque(payloads)
        self.calls = 0

    async def generate_structured(self, prompt: str, response_model: type[T]) -> T:
        self.calls += 1
        if not self._payloads:
            raise AssertionError("Unexpected AI extraction call")
        return response_model(**self._payloads.popleft())


def extraction_payload(extra_evidence: str | None = None) -> dict:
    claims = [
        {
            "subject": "ingestion",
            "predicate": "PUBLISHES_TO",
            "object_entity": "topic",
            "confidence": 0.91,
            "evidence_text": "The Ingestion Service publishes to the Transformed Price Topic.",
        },
        {
            "subject": "aggregator",
            "predicate": "CONSUMES",
            "object_entity": "topic",
            "confidence": 0.92,
            "evidence_text": "The Aggregator Service consumes the Transformed Price Topic.",
        },
    ]
    if extra_evidence is not None:
        claims.append(
            {
                "subject": "ingestion",
                "predicate": "USES",
                "object_entity": "topic",
                "confidence": 0.4,
                "evidence_text": extra_evidence,
            }
        )
    return {
        "entities": [
            {"temporary_id": "ingestion", "entity_type": "SERVICE", "name": "Ingestion Service"},
            {"temporary_id": "aggregator", "entity_type": "SERVICE", "name": "Aggregator Service"},
            {"temporary_id": "topic", "entity_type": "TOPIC", "name": "Transformed Price Topic"},
        ],
        "claims": claims,
        "unresolved_terms": [],
    }


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
        await session.run("MATCH (document:SourceDocument {namespace: 'test'}) WHERE document.filename IN ['phase4-demo.md', 'confirmed-reuse.md'] OPTIONAL MATCH (document)-[:HAS_VERSION]->(version:SourceVersion) OPTIONAL MATCH (version)-[:HAS_CHUNK]->(chunk:SourceChunk) OPTIONAL MATCH (chunk)<-[:FROM_CHUNK]-(evidence:Evidence) DETACH DELETE evidence, chunk, version, document")
        await session.run("MATCH (claim:Claim)-[:SUBJECT]->(entity:Entity) WHERE entity.id IN ['test:service:ingestion-service', 'test:service:aggregator-service', 'test:service:aggregator'] OPTIONAL MATCH (claim)-[:SUPPORTED_BY]->(evidence:Evidence) DETACH DELETE evidence, claim")
        await session.run("MATCH (mention:EntityMention {namespace: 'test'}) DETACH DELETE mention")
        await session.run("MATCH (batch:LearningBatch {namespace: 'test'}) DETACH DELETE batch")
        await session.run("MATCH (binding:AliasBinding)-[:RESOLVED_TO]->(entity:Entity {namespace: 'test'}) DETACH DELETE binding")
        await session.run("MATCH (source:KnowledgeSource) WHERE source.id STARTS WITH 'test:source:' DETACH DELETE source")
        await session.run("MATCH (entity:Entity) WHERE entity.id STARTS WITH 'test:service:ingestion-service' OR entity.id STARTS WITH 'test:topic:transformed-price-topic' OR entity.id STARTS WITH 'test:service:aggregator-service' DETACH DELETE entity")
        await session.run("MATCH (entity:Entity {id: 'test:service:aggregator'}) DETACH DELETE entity")


async def build_service(client: Neo4jClient, tmp_path: Path, ai_client: FakeStructuredAIClient) -> FileIngestionService:
    upload_dir = tmp_path / "uploads"
    return FileIngestionService(
        ai_client=ai_client,
        source_repository=SourceRepository(client),
        document_repository=DocumentRepository(client),
        entity_repository=EntityRepository(client),
        claim_repository=ClaimRepository(client),
        upload_directory=str(upload_dir),
        max_upload_size_mb=10,
        max_chunk_chars=6000,
        max_chunks_per_document=20,
    )


def demo_content(extra: str = "") -> bytes:
    return f"""# Price Event Flow

The Transformed Price Topic is a Kafka topic.

The Ingestion Service publishes to the Transformed Price Topic.

The Aggregator Service consumes the Transformed Price Topic.
{extra}""".encode("utf-8")


def test_file_ingestion_versioning_duplicate_detection_and_provenance(tmp_path: Path) -> None:
    async def scenario() -> None:
        client = await make_client()
        try:
            await cleanup(client)
            entity_repository = EntityRepository(client)
            await entity_repository.create(
                Entity(
                    id="test:service:aggregator",
                    entity_type="SERVICE",
                    canonical_name="Aggregator Service",
                    namespace="test",
                    status=EntityStatus.ACTIVE,
                )
            )
            ai = FakeStructuredAIClient([extraction_payload(extra_evidence="Unsupported paraphrase")])
            service = await build_service(client, tmp_path, ai)

            first = await service.ingest(demo_content(), "phase4-demo.md", namespace="test")

            assert first.status == "INGESTED"
            assert first.chunks_processed == 1
            assert first.entities_created == 2
            assert first.entities_reused == 1
            assert first.claims_created == 2
            assert first.evidence_created == 2
            assert first.claims_rejected == 1
            assert ai.calls == 1

            document_repository = DocumentRepository(client)
            document = await document_repository.get_document_by_external_id(
                FILE_UPLOAD_SOURCE_ID,
                normalize_filename("phase4-demo.md"),
                namespace="test",
            )
            assert document is not None
            assert document.id == stable_source_document_id("phase4-demo.md", "test")
            assert document.latest_version == 1

            async with client.session() as session:
                relationships = await (
                    await session.run(
                        """
                        MATCH (:Claim)-[:SUPPORTED_BY]->(evidence:Evidence)-[:FROM_SOURCE]->(:KnowledgeSource {id: $source_id})
                        MATCH (evidence)-[:FROM_CHUNK]->(:SourceChunk)<-[:HAS_CHUNK]-(:SourceVersion)<-[:HAS_VERSION]-(:SourceDocument {id: $document_id})
                        RETURN count(evidence) AS count
                        """,
                        source_id=FILE_UPLOAD_SOURCE_ID,
                        document_id=document.id,
                    )
                ).single()
                versions = await (
                    await session.run(
                        "MATCH (:SourceDocument {id: $document_id})-[:HAS_VERSION]->(version:SourceVersion) RETURN count(version) AS count",
                        document_id=document.id,
                    )
                ).single()
            assert relationships is not None
            assert relationships["count"] == 2
            assert versions is not None
            assert versions["count"] == 1

            unchanged = await service.ingest(demo_content(), "phase4-demo.md", namespace="test")
            assert unchanged.status == "UNCHANGED"
            assert unchanged.chunks_processed == 0
            assert ai.calls == 1

            ai._payloads.append(extraction_payload())
            changed = await service.ingest(
                demo_content("\nThe Ingestion Service publishes to the Transformed Price Topic.\n"),
                "phase4-demo.md",
                namespace="test",
            )
            assert changed.status == "INGESTED"
            assert changed.version_id != first.version_id

            async with client.session() as session:
                version_count = await (
                    await session.run(
                        "MATCH (:SourceDocument {id: $document_id})-[:HAS_VERSION]->(version:SourceVersion) RETURN count(version) AS count",
                        document_id=document.id,
                    )
                ).single()
                current = await (
                    await session.run(
                        "MATCH (document:SourceDocument {id: $document_id}) RETURN document.latest_version AS latest",
                        document_id=document.id,
                    )
                ).single()
            assert version_count is not None
            assert version_count["count"] == 2
            assert current is not None
            assert current["latest"] == 2
        finally:
            await cleanup(client)
            await client.close()

    run(scenario())


def test_ingestion_reuses_existing_confirmed_claim_without_downgrade(tmp_path: Path) -> None:
    async def scenario() -> None:
        client = await make_client()
        try:
            await cleanup(client)
            entity_repository = EntityRepository(client)
            claim_repository = ClaimRepository(client)
            source_repository = SourceRepository(client)
            ingestion = await entity_repository.create(
                Entity(id="test:service:ingestion-service", entity_type="SERVICE", canonical_name="Ingestion Service", namespace="test")
            )
            topic = await entity_repository.create(
                Entity(id="test:topic:transformed-price-topic", entity_type="TOPIC", canonical_name="Transformed Price Topic", namespace="test")
            )
            await source_repository.create(
                KnowledgeSource(id="test:source:confirmed-reuse", source_type=SourceType.SYSTEM, title="Confirmed Reuse")
            )
            confirmed = await claim_repository.create(
                Claim(
                    id="test:claim:confirmed-reuse",
                    subject_entity_id=ingestion.id,
                    predicate="PUBLISHES_TO",
                    object_entity_id=topic.id,
                    confidence=1.0,
                    status=ClaimStatus.CONFIRMED,
                )
            )
            await claim_repository.add_evidence(
                Evidence(
                    id="test:evidence:confirmed-reuse",
                    claim_id=confirmed.id,
                    source_id="test:source:confirmed-reuse",
                    excerpt="Existing evidence",
                )
            )

            ai = FakeStructuredAIClient([extraction_payload()])
            service = await build_service(client, tmp_path, ai)
            result = await service.ingest(demo_content(), "confirmed-reuse.md", namespace="test")

            assert result.claims_reused >= 1
            reloaded = await claim_repository.get(confirmed.id)
            assert reloaded is not None
            assert reloaded.status == ClaimStatus.CONFIRMED
            async with client.session() as session:
                evidence_count = await (
                    await session.run(
                        "MATCH (:Claim {id: $claim_id})-[:SUPPORTED_BY]->(evidence:Evidence)-[:FROM_CHUNK]->(:SourceChunk) RETURN count(evidence) AS count",
                        claim_id=confirmed.id,
                    )
                ).single()
            assert evidence_count is not None
            assert evidence_count["count"] == 1
        finally:
            await cleanup(client)
            await client.close()

    run(scenario())
