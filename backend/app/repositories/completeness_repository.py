from typing import Any

from app.completeness.models import GapFinding
from app.completeness.rules import (
    CONSUMER_PREDICATES,
    COUNTED_CLAIM_STATUSES,
    MISSING_CONSUMER_GAP_TYPE,
    MISSING_CONSUMER_RULE_ID,
    MISSING_OWNER_GAP_TYPE,
    MISSING_OWNER_RULE_ID,
    MISSING_PRODUCER_GAP_TYPE,
    MISSING_PRODUCER_RULE_ID,
    OWNER_PREDICATES,
    OWNABLE_ENTITY_TYPES,
    PRODUCER_PREDICATES,
    TARGET_ENTITY_TYPES,
)
from app.db.neo4j import Neo4jClient
from app.domain.enums import GapPriority


class CompletenessRepository:
    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    async def find_missing_consumers(self, namespace: str) -> list[GapFinding]:
        records = await self._find_targets_with_present_and_missing_predicates(
            namespace=namespace,
            present_predicates=PRODUCER_PREDICATES,
            missing_predicates=CONSUMER_PREDICATES,
        )
        return [
            GapFinding(
                rule_id=MISSING_CONSUMER_RULE_ID,
                gap_type=MISSING_CONSUMER_GAP_TYPE,
                entity_id=record["entity_id"],
                entity_name=record["entity_name"],
                description=f"No consumer is currently known for {record['entity_name']}.",
                priority=GapPriority.HIGH,
            )
            for record in records
        ]

    async def find_missing_producers(self, namespace: str) -> list[GapFinding]:
        records = await self._find_targets_with_present_and_missing_predicates(
            namespace=namespace,
            present_predicates=CONSUMER_PREDICATES,
            missing_predicates=PRODUCER_PREDICATES,
        )
        return [
            GapFinding(
                rule_id=MISSING_PRODUCER_RULE_ID,
                gap_type=MISSING_PRODUCER_GAP_TYPE,
                entity_id=record["entity_id"],
                entity_name=record["entity_name"],
                description=f"No producer is currently known for {record['entity_name']}.",
                priority=GapPriority.HIGH,
            )
            for record in records
        ]

    async def find_missing_owners(self, namespace: str) -> list[GapFinding]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (entity:Entity {namespace: $namespace, status: 'ACTIVE'})
                WHERE entity.entity_type IN $ownable_entity_types
                  AND NOT EXISTS {
                    MATCH (claim:Claim)-[:SUBJECT]->(team:Entity)
                    MATCH (claim)-[:OBJECT]->(entity)
                    MATCH (claim)-[:SUPPORTED_BY]->(evidence:Evidence)
                    WHERE claim.status IN $claim_statuses
                      AND claim.predicate IN $owner_predicates
                      AND team.namespace = $namespace
                      AND team.status = 'ACTIVE'
                      AND team.entity_type = 'TEAM'
                      AND coalesce(evidence.is_current, true)
                  }
                RETURN entity.id AS entity_id, entity.canonical_name AS entity_name
                ORDER BY entity.canonical_name, entity.id
                """,
                namespace=namespace,
                ownable_entity_types=OWNABLE_ENTITY_TYPES,
                owner_predicates=OWNER_PREDICATES,
                claim_statuses=COUNTED_CLAIM_STATUSES,
            )
            records = await result.data()

        return [
            GapFinding(
                rule_id=MISSING_OWNER_RULE_ID,
                gap_type=MISSING_OWNER_GAP_TYPE,
                entity_id=record["entity_id"],
                entity_name=record["entity_name"],
                description=f"No owning team is currently known for {record['entity_name']}.",
                priority=GapPriority.MEDIUM,
            )
            for record in records
        ]

    async def detect_all(self, namespace: str) -> list[GapFinding]:
        return [
            *await self.find_missing_consumers(namespace),
            *await self.find_missing_producers(namespace),
            *await self.find_missing_owners(namespace),
        ]

    async def _find_targets_with_present_and_missing_predicates(
        self,
        namespace: str,
        present_predicates: list[str],
        missing_predicates: list[str],
    ) -> list[dict[str, Any]]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (entity:Entity {namespace: $namespace, status: 'ACTIVE'})
                WHERE entity.entity_type IN $target_entity_types
                  AND EXISTS {
                    MATCH (present:Claim)-[:SUPPORTED_BY]->(present_evidence:Evidence)
                    MATCH (present)-[:SUBJECT]->(:Entity {namespace: $namespace, status: 'ACTIVE'})
                    MATCH (present)-[:OBJECT]->(entity)
                    WHERE present.status IN $claim_statuses
                      AND present.predicate IN $present_predicates
                      AND coalesce(present_evidence.is_current, true)
                  }
                  AND NOT EXISTS {
                    MATCH (missing:Claim)-[:SUPPORTED_BY]->(missing_evidence:Evidence)
                    MATCH (missing)-[:SUBJECT]->(:Entity {namespace: $namespace, status: 'ACTIVE'})
                    MATCH (missing)-[:OBJECT]->(entity)
                    WHERE missing.status IN $claim_statuses
                      AND missing.predicate IN $missing_predicates
                      AND coalesce(missing_evidence.is_current, true)
                  }
                RETURN entity.id AS entity_id, entity.canonical_name AS entity_name
                ORDER BY entity.canonical_name, entity.id
                """,
                namespace=namespace,
                target_entity_types=TARGET_ENTITY_TYPES,
                present_predicates=present_predicates,
                missing_predicates=missing_predicates,
                claim_statuses=COUNTED_CLAIM_STATUSES,
            )
            return await result.data()
