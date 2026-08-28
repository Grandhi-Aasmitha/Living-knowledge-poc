from typing import Any

from app.db.neo4j import Neo4jClient
from app.domain.entity import Entity


def _entity_from_node(node: Any) -> Entity:
    return Entity(**dict(node))


class EntityRepository:
    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    async def create(self, entity: Entity) -> Entity:
        properties = entity.model_dump(mode="json")
        async with self._client.session() as session:
            result = await session.run(
                """
                MERGE (entity:Entity {id: $id})
                ON CREATE SET entity = $properties
                RETURN entity
                """,
                id=entity.id,
                properties=properties,
            )
            record = await result.single()

        if record is None:
            raise ValueError("Entity was not created")
        return _entity_from_node(record["entity"])

    async def get(self, entity_id: str) -> Entity | None:
        async with self._client.session() as session:
            result = await session.run(
                "MATCH (entity:Entity {id: $id}) RETURN entity",
                id=entity_id,
            )
            record = await result.single()

        if record is None:
            return None
        return _entity_from_node(record["entity"])

    async def exists(self, entity_id: str) -> bool:
        async with self._client.session() as session:
            result = await session.run(
                "MATCH (entity:Entity {id: $id}) RETURN count(entity) > 0 AS exists",
                id=entity_id,
            )
            record = await result.single()

        return bool(record is not None and record["exists"])
