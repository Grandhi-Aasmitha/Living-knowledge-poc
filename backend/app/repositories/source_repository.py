from typing import Any

from app.db.neo4j import Neo4jClient
from app.domain.source import KnowledgeSource


def _source_from_node(node: Any) -> KnowledgeSource:
    return KnowledgeSource(**dict(node))


class SourceRepository:
    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    async def create(self, source: KnowledgeSource) -> KnowledgeSource:
        properties = source.model_dump(mode="json")
        async with self._client.session() as session:
            result = await session.run(
                """
                MERGE (source:KnowledgeSource {id: $id})
                ON CREATE SET source = $properties
                RETURN source
                """,
                id=source.id,
                properties=properties,
            )
            record = await result.single()

        if record is None:
            raise ValueError("KnowledgeSource was not created")
        return _source_from_node(record["source"])

    async def get(self, source_id: str) -> KnowledgeSource | None:
        async with self._client.session() as session:
            result = await session.run(
                "MATCH (source:KnowledgeSource {id: $id}) RETURN source",
                id=source_id,
            )
            record = await result.single()

        if record is None:
            return None
        return _source_from_node(record["source"])
