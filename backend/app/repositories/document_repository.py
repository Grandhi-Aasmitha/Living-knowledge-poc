from typing import Any

from app.db.neo4j import Neo4jClient
from app.documents.models import SourceChunk, SourceDocument, SourceVersion


def _document_from_node(node: Any) -> SourceDocument:
    return SourceDocument(**dict(node))


def _version_from_node(node: Any) -> SourceVersion:
    return SourceVersion(**dict(node))


class DocumentRepository:
    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    async def get_document(self, document_id: str) -> SourceDocument | None:
        async with self._client.session() as session:
            result = await session.run("MATCH (document:SourceDocument {id: $id}) RETURN document", id=document_id)
            record = await result.single()
        return None if record is None else _document_from_node(record["document"])

    async def get_document_by_external_id(self, source_id: str, external_id: str) -> SourceDocument | None:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (:KnowledgeSource {id: $source_id})-[:HAS_DOCUMENT]->(document:SourceDocument {external_id: $external_id})
                RETURN document
                ORDER BY document.id
                LIMIT 1
                """,
                source_id=source_id,
                external_id=external_id,
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

    async def mark_document_current(self, document_id: str, version_number: int, content_hash: str, updated_at: Any) -> SourceDocument:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (document:SourceDocument {id: $document_id})
                SET document.latest_version = $version_number,
                    document.current_content_hash = $content_hash,
                    document.updated_at = $updated_at
                RETURN document
                """,
                document_id=document_id,
                version_number=version_number,
                content_hash=content_hash,
                updated_at=updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
            )
            record = await result.single()
        if record is None:
            raise ValueError("SourceDocument was not updated")
        return _document_from_node(record["document"])
