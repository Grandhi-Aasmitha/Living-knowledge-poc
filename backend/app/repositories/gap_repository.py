from datetime import UTC, datetime
from typing import Any

from app.db.neo4j import Neo4jClient
from app.domain.enums import GapStatus
from app.domain.gap import KnowledgeGap


def _gap_from_node(node: Any) -> KnowledgeGap:
    return KnowledgeGap(**dict(node))


class GapRepository:
    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    async def create(self, gap: KnowledgeGap) -> KnowledgeGap:
        properties = gap.model_dump(mode="json")
        async with self._client.session() as session:
            entity_result = await session.run(
                "MATCH (entity:Entity {id: $id}) RETURN count(entity) > 0 AS exists",
                id=gap.entity_id,
            )
            entity_record = await entity_result.single()
            if entity_record is None or not entity_record["exists"]:
                raise ValueError(f"Entity does not exist: {gap.entity_id}")

            result = await session.run(
                """
                MATCH (entity:Entity {id: $entity_id})
                MERGE (gap:KnowledgeGap {id: $id})
                ON CREATE SET gap = $properties
                MERGE (gap)-[:ABOUT]->(entity)
                RETURN gap
                """,
                entity_id=gap.entity_id,
                id=gap.id,
                properties=properties,
            )
            record = await result.single()

        if record is None:
            raise ValueError("KnowledgeGap was not created")
        return _gap_from_node(record["gap"])

    async def get(self, gap_id: str) -> KnowledgeGap | None:
        async with self._client.session() as session:
            result = await session.run(
                "MATCH (gap:KnowledgeGap {id: $id}) RETURN gap",
                id=gap_id,
            )
            record = await result.single()

        if record is None:
            return None
        return _gap_from_node(record["gap"])

    async def list_open(self) -> list[KnowledgeGap]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (gap:KnowledgeGap {status: $status})
                RETURN gap
                ORDER BY gap.created_at, gap.id
                """,
                status=GapStatus.OPEN.value,
            )
            records = await result.data()

        return [_gap_from_node(record["gap"]) for record in records]

    async def find_open_for_entity_and_type(self, entity_id: str, gap_type: str) -> KnowledgeGap | None:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (gap:KnowledgeGap {entity_id: $entity_id, gap_type: $gap_type, status: $status})
                RETURN gap
                ORDER BY gap.created_at, gap.id
                LIMIT 1
                """,
                entity_id=entity_id,
                gap_type=gap_type,
                status=GapStatus.OPEN.value,
            )
            record = await result.single()

        if record is None:
            return None
        return _gap_from_node(record["gap"])

    async def list_automatic_for_namespace(self, namespace: str) -> list[KnowledgeGap]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (gap:KnowledgeGap)-[:ABOUT]->(entity:Entity {namespace: $namespace})
                WHERE gap.detection_rule_id IS NOT NULL
                RETURN gap
                ORDER BY gap.created_at, gap.id
                """,
                namespace=namespace,
            )
            records = await result.data()

        return [_gap_from_node(record["gap"]) for record in records]

    async def resolve(self, gap_id: str) -> KnowledgeGap | None:
        resolved_at = datetime.now(UTC).isoformat()
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (gap:KnowledgeGap {id: $id})
                SET gap.status = $status,
                    gap.resolved_at = coalesce(gap.resolved_at, $resolved_at)
                RETURN gap
                """,
                id=gap_id,
                status=GapStatus.RESOLVED.value,
                resolved_at=resolved_at,
            )
            record = await result.single()

        if record is None:
            return None
        return _gap_from_node(record["gap"])

    async def reopen(self, gap_id: str, detected_at: datetime) -> KnowledgeGap | None:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (gap:KnowledgeGap {id: $id})
                SET gap.status = $status,
                    gap.resolved_at = NULL,
                    gap.last_detected_at = $detected_at
                RETURN gap
                """,
                id=gap_id,
                status=GapStatus.OPEN.value,
                detected_at=detected_at.isoformat(),
            )
            record = await result.single()

        if record is None:
            return None
        return _gap_from_node(record["gap"])

    async def touch_detection(self, gap_id: str, detected_at: datetime) -> KnowledgeGap | None:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (gap:KnowledgeGap {id: $id})
                SET gap.last_detected_at = $detected_at
                RETURN gap
                """,
                id=gap_id,
                detected_at=detected_at.isoformat(),
            )
            record = await result.single()

        if record is None:
            return None
        return _gap_from_node(record["gap"])
