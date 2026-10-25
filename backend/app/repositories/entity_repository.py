from datetime import UTC, datetime
from typing import Any

from app.db.neo4j import Neo4jClient
from app.domain.entity import Entity
from app.domain.identifiers import sha256_text


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

    async def find_by_name_or_alias(self, name: str, namespace: str) -> Entity | None:
        normalized_name = name.casefold()
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (entity:Entity {namespace: $namespace})
                WHERE toLower(entity.canonical_name) = $name
                   OR any(alias IN coalesce(entity.aliases, []) WHERE toLower(alias) = $name)
                RETURN entity
                ORDER BY entity.id
                LIMIT 1
                """,
                name=normalized_name,
                namespace=namespace,
            )
            record = await result.single()

        if record is None:
            return None
        return _entity_from_node(record["entity"])

    async def list_active_for_resolution(
        self,
        namespace: str,
        entity_types: list[str],
    ) -> list[Entity]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (entity:Entity {namespace: $namespace, status: 'ACTIVE'})
                WHERE entity.entity_type IN $entity_types
                RETURN entity
                ORDER BY entity.canonical_name, entity.id
                """,
                namespace=namespace,
                entity_types=entity_types,
            )
            records = await result.data()
        return [_entity_from_node(record["entity"]) for record in records]

    async def list_active_in_namespace(self, namespace: str) -> list[Entity]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (entity:Entity {namespace: $namespace, status: 'ACTIVE'})
                RETURN entity ORDER BY entity.canonical_name, entity.id
                """,
                namespace=namespace,
            )
            records = await result.data()
        return [_entity_from_node(record["entity"]) for record in records]

    async def add_alias(self, entity_id: str, alias: str, mention_id: str | None = None, reason: str | None = None) -> Entity:
        async with self._client.session() as session:
            return await session.execute_write(self.add_alias_in_transaction, entity_id, alias, mention_id, reason)

    @staticmethod
    async def add_alias_in_transaction(tx: Any, entity_id: str, alias: str, mention_id: str | None = None, reason: str | None = None) -> Entity:
        cleaned_alias = alias.strip()
        if not cleaned_alias:
            raise ValueError("alias must not be empty")
        result = await tx.run(
                """
                MATCH (entity:Entity {id: $entity_id})
                SET entity.lock_revision = coalesce(entity.lock_revision, 0) + 1
                WITH entity
                WHERE NOT EXISTS {
                    MATCH (other:Entity {namespace: entity.namespace, entity_type: entity.entity_type, status: 'ACTIVE'})
                    WHERE other.id <> entity.id AND (toLower(other.canonical_name) = toLower($alias)
                        OR any(name IN coalesce(other.aliases, []) WHERE toLower(name) = toLower($alias)))
                }
                MERGE (binding:AliasBinding {id: $binding_prefix + entity.namespace + ':' + entity.entity_type})
                ON CREATE SET binding.entity_id = entity.id, binding.name = $alias,
                              binding.mention_id = $mention_id, binding.reason = $reason
                SET binding.lock_revision = coalesce(binding.lock_revision, 0) + 1
                WITH entity, binding WHERE binding.entity_id = entity.id
                MERGE (binding)-[:RESOLVED_TO]->(entity)
                WITH entity,
                     any(existing IN coalesce(entity.aliases, []) WHERE toLower(existing) = toLower($alias)) AS alias_exists,
                     toLower(entity.canonical_name) = toLower($alias) AS canonical_matches
                SET entity.aliases = CASE
                    WHEN alias_exists OR canonical_matches THEN coalesce(entity.aliases, [])
                    ELSE coalesce(entity.aliases, []) + $alias
                END,
                entity.updated_at = CASE WHEN alias_exists OR canonical_matches THEN entity.updated_at ELSE $updated_at END
                RETURN entity
                """,
                entity_id=entity_id,
                alias=cleaned_alias,
                updated_at=datetime.now(UTC).isoformat(),
                binding_prefix=f"alias:{sha256_text(cleaned_alias.casefold())}:",
                mention_id=mention_id, reason=reason,
            )
        record = await result.single()
        if record is None:
            raise ValueError("Entity is unavailable or the name already belongs to another active entity; reconcile the duplicate before teaching this alias")
        return _entity_from_node(record["entity"])
