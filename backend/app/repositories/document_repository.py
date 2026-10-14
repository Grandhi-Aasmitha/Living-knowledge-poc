from typing import Any

from app.db.neo4j import Neo4jClient
from app.documents.models import SourceChunk, SourceDocument, SourceVersion


def _document_from_node(node: Any) -> SourceDocument:
    return SourceDocument(**dict(node))


def _version_from_node(node: Any) -> SourceVersion:
    properties = dict(node)
    properties.setdefault("processing_status", "COMPLETE")
    return SourceVersion(**properties)


class DocumentRepository:
    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    async def get_document(self, document_id: str) -> SourceDocument | None:
        async with self._client.session() as session:
            result = await session.run("MATCH (document:SourceDocument {id: $id}) RETURN document", id=document_id)
            record = await result.single()
        return None if record is None else _document_from_node(record["document"])

    async def get_document_by_external_id(self, source_id: str, external_id: str, namespace: str = "tstvs") -> SourceDocument | None:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (:KnowledgeSource {id: $source_id})-[:HAS_DOCUMENT]->(document:SourceDocument {external_id: $external_id})
                WHERE coalesce(document.namespace, 'tstvs') = $namespace
                RETURN document
                ORDER BY document.id
                LIMIT 1
                """,
                source_id=source_id,
                external_id=external_id,
                namespace=namespace,
            )
            record = await result.single()
        return None if record is None else _document_from_node(record["document"])

    async def create_document(self, document: SourceDocument) -> SourceDocument:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (source:KnowledgeSource {id: $source_id})
                MERGE (document:SourceDocument {id: $id})
                ON CREATE SET document = $properties
                MERGE (source)-[:HAS_DOCUMENT]->(document)
                RETURN document
                """,
                source_id=document.source_id,
                id=document.id,
                properties=document.model_dump(mode="json"),
            )
            record = await result.single()
        if record is None:
            raise ValueError("SourceDocument was not created")
        return _document_from_node(record["document"])

    async def create_version(self, version: SourceVersion) -> SourceVersion:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (document:SourceDocument {id: $document_id})
                MERGE (version:SourceVersion {id: $id})
                ON CREATE SET version = $properties
                MERGE (document)-[:HAS_VERSION]->(version)
                RETURN version
                """,
                document_id=version.document_id,
                id=version.id,
                properties=version.model_dump(mode="json"),
            )
            record = await result.single()
        if record is None:
            raise ValueError("SourceVersion was not created")
        return _version_from_node(record["version"])

    async def create_chunks(self, chunks: list[SourceChunk]) -> list[SourceChunk]:
        if not chunks:
            return []
        properties = [chunk.model_dump(mode="json") for chunk in chunks]
        async with self._client.session() as session:
            result = await session.run(
                """
                UNWIND $chunks AS chunk_properties
                MATCH (version:SourceVersion {id: chunk_properties.version_id})
                MERGE (chunk:SourceChunk {id: chunk_properties.id})
                ON CREATE SET chunk = chunk_properties
                MERGE (version)-[:HAS_CHUNK]->(chunk)
                RETURN chunk
                ORDER BY chunk.sequence
                """,
                chunks=properties,
            )
            records = await result.data()
        return [SourceChunk(**dict(record["chunk"])) for record in records]

    async def get_current_version(self, document_id: str) -> SourceVersion | None:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (document:SourceDocument {id: $document_id})-[:HAS_VERSION]->(version:SourceVersion)
                WHERE version.version_number = document.latest_version
                RETURN version
                """,
                document_id=document_id,
            )
            record = await result.single()
        return None if record is None else _version_from_node(record["version"])

    async def list_documents(self) -> list[SourceDocument]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (document:SourceDocument)
                RETURN document
                ORDER BY document.updated_at DESC, document.title
                """
            )
            records = await result.data()
        return [_document_from_node(record["document"]) for record in records]

    async def activate_version_evidence(self, document_id: str, version_id: str) -> None:
        async def activate(tx):
            result = await tx.run(
                """
                MATCH (document:SourceDocument {id: $document_id})
                SET document.lock_revision = coalesce(document.lock_revision, 0) + 1
                WITH document WHERE document.current_version_id = $version_id
                MATCH (document)-[:HAS_VERSION]->(:SourceVersion {id: $version_id})-[:HAS_CHUNK]->(:SourceChunk)<-[:FROM_CHUNK]-(evidence:Evidence)
                SET evidence.is_current = true
                RETURN count(evidence) AS count
                """, document_id=document_id, version_id=version_id,
            )
            await result.consume()
        async with self._client.session() as session:
            await session.execute_write(activate)

    async def mark_document_current(self, document_id: str, version_number: int, content_hash: str, updated_at: Any, version_id: str | None = None) -> SourceDocument:
        async def publish(tx):
            result = await tx.run(
                """
                MATCH (document:SourceDocument {id: $document_id})
                SET document.lock_revision = coalesce(document.lock_revision, 0) + 1
                WITH document
                MATCH (document)-[:HAS_VERSION]->(version:SourceVersion)
                WHERE ($version_id IS NULL AND version.version_number = $version_number) OR version.id = $version_id
                SET document.latest_version = version.version_number,
                    document.current_content_hash = $content_hash,
                    document.current_version_id = version.id,
                    document.updated_at = $updated_at,
                    version.processing_status = 'COMPLETE'
                RETURN document, version.id AS version_id
                """,
                document_id=document_id, version_id=version_id, version_number=version_number,
                content_hash=content_hash,
                updated_at=updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
            )
            record = await result.single()
            if record is None:
                raise ValueError("SourceDocument version was not found")
            await tx.run(
                """
                MATCH (:SourceDocument {id: $document_id})-[:HAS_VERSION]->(version:SourceVersion)-[:HAS_CHUNK]->(:SourceChunk)<-[:FROM_CHUNK]-(evidence:Evidence)
                SET evidence.is_current = version.id = $version_id
                """,
                document_id=document_id, version_id=record["version_id"],
            )
            await tx.run(
                """
                MATCH (batch:LearningBatch {document_id: $document_id})-[:HAS_MENTION]->(mention:EntityMention {status: 'OPEN'})
                WHERE batch.version_id <> $version_id
                SET mention.status = 'SUPERSEDED'
                """,
                document_id=document_id, version_id=record["version_id"],
            )
            return _document_from_node(record["document"])
        async with self._client.session() as session:
            return await session.execute_write(publish)
