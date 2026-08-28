from typing import Any

from app.db.neo4j import Neo4jClient
from app.domain.claim import Claim
from app.domain.evidence import Evidence


def _claim_from_node(node: Any) -> Claim:
    return Claim(**dict(node))


def _evidence_from_node(node: Any) -> Evidence:
    return Evidence(**dict(node))


class ClaimRepository:
    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    async def create(self, claim: Claim) -> Claim:
        async with self._client.session() as session:
            subject_exists = await self._entity_exists(session, claim.subject_entity_id)
            if not subject_exists:
                raise ValueError(f"Subject entity does not exist: {claim.subject_entity_id}")

            if claim.object_entity_id is not None:
                object_exists = await self._entity_exists(session, claim.object_entity_id)
                if not object_exists:
                    raise ValueError(f"Object entity does not exist: {claim.object_entity_id}")

            if claim.scope_entity_id is not None:
                scope_exists = await self._entity_exists(session, claim.scope_entity_id)
                if not scope_exists:
                    raise ValueError(f"Scope entity does not exist: {claim.scope_entity_id}")

            result = await session.run(
                """
                MATCH (subject:Entity {id: $subject_entity_id})
                MERGE (claim:Claim {id: $id})
                ON CREATE SET claim = $properties
                MERGE (claim)-[:SUBJECT]->(subject)
                RETURN claim
                """,
                id=claim.id,
                subject_entity_id=claim.subject_entity_id,
                properties=claim.model_dump(mode="json"),
            )
            record = await result.single()

            if claim.object_entity_id is not None:
                await session.run(
                    """
                    MATCH (claim:Claim {id: $claim_id})
                    MATCH (object:Entity {id: $object_entity_id})
                    MERGE (claim)-[:OBJECT]->(object)
                    """,
                    claim_id=claim.id,
                    object_entity_id=claim.object_entity_id,
                )

            if claim.scope_entity_id is not None:
                await session.run(
                    """
                    MATCH (claim:Claim {id: $claim_id})
                    MATCH (scope:Entity {id: $scope_entity_id})
                    MERGE (claim)-[:SCOPE]->(scope)
                    """,
                    claim_id=claim.id,
                    scope_entity_id=claim.scope_entity_id,
                )

        if record is None:
            raise ValueError("Claim was not created")
        return _claim_from_node(record["claim"])

    async def get(self, claim_id: str) -> Claim | None:
        async with self._client.session() as session:
            result = await session.run(
                "MATCH (claim:Claim {id: $id}) RETURN claim",
                id=claim_id,
            )
            record = await result.single()

        if record is None:
            return None
        return _claim_from_node(record["claim"])

    async def list_for_entity(self, entity_id: str) -> list[Claim]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (claim:Claim)
                WHERE (claim)-[:SUBJECT]->(:Entity {id: $entity_id})
                   OR (claim)-[:OBJECT]->(:Entity {id: $entity_id})
                RETURN DISTINCT claim
                ORDER BY claim.created_at, claim.id
                """,
                entity_id=entity_id,
            )
            records = await result.data()

        return [_claim_from_node(record["claim"]) for record in records]

    async def find_equivalent_active(
        self,
        subject_entity_id: str,
        predicate: str,
        object_entity_id: str | None,
        object_value: str | None,
        scope_entity_id: str | None,
    ) -> Claim | None:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (claim:Claim {subject_entity_id: $subject_entity_id, predicate: $predicate})
                WHERE claim.status IN ['PROPOSED', 'CONFIRMED']
                  AND coalesce(claim.object_entity_id, '') = coalesce($object_entity_id, '')
                  AND coalesce(claim.object_value, '') = coalesce($object_value, '')
                  AND coalesce(claim.scope_entity_id, '') = coalesce($scope_entity_id, '')
                RETURN claim
                ORDER BY CASE claim.status WHEN 'CONFIRMED' THEN 0 ELSE 1 END, claim.created_at, claim.id
                LIMIT 1
                """,
                subject_entity_id=subject_entity_id,
                predicate=predicate,
                object_entity_id=object_entity_id,
                object_value=object_value,
                scope_entity_id=scope_entity_id,
            )
            record = await result.single()
        return None if record is None else _claim_from_node(record["claim"])

    async def add_evidence(self, evidence: Evidence) -> Evidence:
        async with self._client.session() as session:
            claim_result = await session.run(
                "MATCH (claim:Claim {id: $id}) RETURN count(claim) > 0 AS exists",
                id=evidence.claim_id,
            )
            claim_record = await claim_result.single()
            if claim_record is None or not claim_record["exists"]:
                raise ValueError(f"Claim does not exist: {evidence.claim_id}")

            source_result = await session.run(
                "MATCH (source:KnowledgeSource {id: $id}) RETURN count(source) > 0 AS exists",
                id=evidence.source_id,
            )
            source_record = await source_result.single()
            if source_record is None or not source_record["exists"]:
                raise ValueError(f"KnowledgeSource does not exist: {evidence.source_id}")

            if evidence.source_chunk_id is not None:
                chunk_result = await session.run(
                    "MATCH (chunk:SourceChunk {id: $id}) RETURN count(chunk) > 0 AS exists",
                    id=evidence.source_chunk_id,
                )
                chunk_record = await chunk_result.single()
                if chunk_record is None or not chunk_record["exists"]:
                    raise ValueError(f"SourceChunk does not exist: {evidence.source_chunk_id}")

            result = await session.run(
                """
                MATCH (claim:Claim {id: $claim_id})
                MATCH (source:KnowledgeSource {id: $source_id})
                OPTIONAL MATCH (chunk:SourceChunk {id: $source_chunk_id})
                MERGE (evidence:Evidence {id: $id})
                ON CREATE SET evidence = $properties
                MERGE (claim)-[:SUPPORTED_BY]->(evidence)
                MERGE (evidence)-[:FROM_SOURCE]->(source)
                FOREACH (_ IN CASE WHEN chunk IS NULL THEN [] ELSE [1] END |
                    MERGE (evidence)-[:FROM_CHUNK]->(chunk)
                )
                RETURN evidence
                """,
                claim_id=evidence.claim_id,
                source_id=evidence.source_id,
                source_chunk_id=evidence.source_chunk_id,
                id=evidence.id,
                properties=evidence.model_dump(mode="json"),
            )
            record = await result.single()

        if record is None:
            raise ValueError("Evidence was not created")
        return _evidence_from_node(record["evidence"])

    async def _entity_exists(self, session: Any, entity_id: str) -> bool:
        result = await session.run(
            "MATCH (entity:Entity {id: $id}) RETURN count(entity) > 0 AS exists",
            id=entity_id,
        )
        record = await result.single()
        return bool(record is not None and record["exists"])
