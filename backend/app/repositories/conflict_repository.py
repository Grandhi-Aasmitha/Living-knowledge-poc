from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.conflicts.models import (
    ConflictClaimDetail,
    ConflictDetail,
    ConflictEvidenceSummary,
    ConflictFinding,
    ConflictSummary,
    KnowledgeConflict,
)
from app.conflicts.rules import COUNTED_CLAIM_STATUSES, MULTIPLE_OWNERS_RULE_ID, MULTIPLE_PART_OF_RULE_ID, OWNABLE_ENTITY_TYPES
from app.db.neo4j import Neo4jClient
from app.domain.claim import Claim
from app.domain.enums import ClaimStatus, ConflictResolutionType, ConflictStatus, SourceType
from app.domain.evidence import Evidence
from app.domain.source import KnowledgeSource


def _conflict_from_node(node: Any) -> KnowledgeConflict:
    return KnowledgeConflict(**dict(node))


class ConflictRepository:
    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    async def detect_multiple_owners(self, namespace: str) -> list[ConflictFinding]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (target:Entity {namespace: $namespace, status: 'ACTIVE'})
                WHERE target.entity_type IN $ownable_entity_types
                MATCH (claim:Claim {predicate: 'OWNS'})-[:OBJECT]->(target)
                MATCH (claim)-[:SUBJECT]->(team:Entity {namespace: $namespace, status: 'ACTIVE', entity_type: 'TEAM'})
                WHERE claim.status IN $claim_statuses
                  AND EXISTS { MATCH (claim)-[:SUPPORTED_BY]->(evidence:Evidence) WHERE coalesce(evidence.is_current, true) }
                WITH target, collect(DISTINCT {claim_id: claim.id, team_id: team.id}) AS ownerships
                WITH target, ownerships, size([team_id IN collect(DISTINCT ownerships[0].team_id) | team_id]) AS unused
                UNWIND ownerships AS ownership
                WITH target, collect(DISTINCT ownership.team_id) AS teams, collect(DISTINCT ownership.claim_id) AS claim_ids
                WHERE size(teams) >= 2 AND size(claim_ids) >= 2
                RETURN target.canonical_name AS entity_name, claim_ids
                ORDER BY entity_name
                """,
                namespace=namespace,
                ownable_entity_types=OWNABLE_ENTITY_TYPES,
                claim_statuses=COUNTED_CLAIM_STATUSES,
            )
            records = await result.data()
        return [
            ConflictFinding(
                rule_id=MULTIPLE_OWNERS_RULE_ID,
                namespace=namespace,
                description=f"Multiple owning teams are currently recorded for {record['entity_name']}.",
                claim_ids=record["claim_ids"],
            )
            for record in records
        ]

    async def detect_multiple_part_of(self, namespace: str) -> list[ConflictFinding]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (subject:Entity {namespace: $namespace, status: 'ACTIVE'})
                MATCH (claim:Claim {predicate: 'PART_OF'})-[:SUBJECT]->(subject)
                MATCH (claim)-[:OBJECT]->(parent:Entity {namespace: $namespace, status: 'ACTIVE'})
                WHERE claim.status IN $claim_statuses
                  AND EXISTS { MATCH (claim)-[:SUPPORTED_BY]->(evidence:Evidence) WHERE coalesce(evidence.is_current, true) }
                WITH subject, collect(DISTINCT parent.id) AS parents, collect(DISTINCT claim.id) AS claim_ids
                WHERE size(parents) >= 2 AND size(claim_ids) >= 2
                RETURN subject.canonical_name AS entity_name, claim_ids
                ORDER BY entity_name
                """,
                namespace=namespace,
                claim_statuses=COUNTED_CLAIM_STATUSES,
            )
            records = await result.data()
        return [
            ConflictFinding(
                rule_id=MULTIPLE_PART_OF_RULE_ID,
                namespace=namespace,
                description=f"Multiple parent entities are currently recorded for {record['entity_name']}.",
                claim_ids=record["claim_ids"],
            )
            for record in records
        ]

    async def detect_all(self, namespace: str) -> list[ConflictFinding]:
        return [*await self.detect_multiple_owners(namespace), *await self.detect_multiple_part_of(namespace)]

    async def create(self, conflict: KnowledgeConflict, claim_ids: list[str]) -> KnowledgeConflict:
        async with self._client.session() as session:
            result = await session.run(
                """
                MERGE (conflict:KnowledgeConflict {id: $id})
                ON CREATE SET conflict = $properties
                WITH conflict
                MATCH (claim:Claim)
                WHERE claim.id IN $claim_ids
                MERGE (conflict)-[:INVOLVES]->(claim)
                WITH DISTINCT conflict
                RETURN conflict
                """,
                id=conflict.id,
                properties=conflict.model_dump(mode="json"),
                claim_ids=claim_ids,
            )
            record = await result.single()
        if record is None:
            raise ValueError("KnowledgeConflict was not created")
        return _conflict_from_node(record["conflict"])

    async def get(self, conflict_id: str) -> ConflictDetail | None:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (conflict:KnowledgeConflict {id: $id})
                OPTIONAL MATCH (conflict)-[:INVOLVES]->(claim:Claim)
                OPTIONAL MATCH (claim)-[:SUBJECT]->(subject:Entity)
                OPTIONAL MATCH (claim)-[:OBJECT]->(object:Entity)
                OPTIONAL MATCH (claim)-[:SUPPORTED_BY]->(evidence:Evidence)-[:FROM_SOURCE]->(source:KnowledgeSource)
                OPTIONAL MATCH (evidence)-[:FROM_CHUNK]->(chunk:SourceChunk)<-[:HAS_CHUNK]-(version:SourceVersion)<-[:HAS_VERSION]-(document:SourceDocument)
                WITH conflict, claim, subject, object, evidence, source, chunk, version, document
                ORDER BY claim.id, evidence.id
                WITH conflict, claim, subject, object,
                     collect(CASE WHEN evidence IS NULL THEN NULL ELSE {
                        id: evidence.id,
                        excerpt: evidence.excerpt,
                        locator: evidence.locator,
                        source_id: source.id,
                        source_type: source.source_type,
                        source_title: source.title,
                        document_title: document.title,
                        document_version: version.version_number,
                        chunk_locator: chunk.locator
                     } END) AS evidence_rows
                WITH conflict, collect(CASE WHEN claim IS NULL THEN NULL ELSE {
                    claim_id: claim.id,
                    subject_entity_id: subject.id,
                    subject_name: subject.canonical_name,
                    predicate: claim.predicate,
                    object_entity_id: object.id,
                    object_name: object.canonical_name,
                    status: claim.status,
                    confidence: claim.confidence,
                    created_at: claim.created_at,
                    evidence_count: size([row IN evidence_rows WHERE row IS NOT NULL]),
                    evidence: [row IN evidence_rows WHERE row IS NOT NULL]
                } END) AS claims
                RETURN conflict, [claim IN claims WHERE claim IS NOT NULL] AS claims
                """,
                id=conflict_id,
            )
            record = await result.single()
        if record is None:
            return None
        conflict = _conflict_from_node(record["conflict"])
        return ConflictDetail(
            **conflict.model_dump(),
            claims=[
                ConflictClaimDetail(
                    **{key: value for key, value in claim.items() if key != "evidence"},
                    evidence=[ConflictEvidenceSummary(**evidence) for evidence in claim["evidence"]],
                )
                for claim in record["claims"]
            ],
        )

    async def get_conflict(self, conflict_id: str) -> KnowledgeConflict | None:
        async with self._client.session() as session:
            result = await session.run("MATCH (conflict:KnowledgeConflict {id: $id}) RETURN conflict", id=conflict_id)
            record = await result.single()
        return None if record is None else _conflict_from_node(record["conflict"])

    async def list(self, namespace: str, status: ConflictStatus | None = ConflictStatus.OPEN) -> list[ConflictSummary]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (conflict:KnowledgeConflict {namespace: $namespace})
                WHERE $status IS NULL OR conflict.status = $status
                OPTIONAL MATCH (conflict)-[:INVOLVES]->(claim:Claim)
                RETURN conflict, count(DISTINCT claim) AS claim_count
                ORDER BY conflict.last_detected_at DESC, conflict.id
                """,
                namespace=namespace,
                status=None if status is None else status.value,
            )
            records = await result.data()
        summaries = []
        for record in records:
            conflict = _conflict_from_node(record["conflict"])
            summaries.append(ConflictSummary(**conflict.model_dump(), claim_count=record["claim_count"]))
        return summaries

    async def list_open(self, namespace: str) -> list[KnowledgeConflict]:
        async with self._client.session() as session:
            result = await session.run(
                "MATCH (conflict:KnowledgeConflict {namespace: $namespace, status: 'OPEN'}) RETURN conflict ORDER BY conflict.id",
                namespace=namespace,
            )
            records = await result.data()
        return [_conflict_from_node(record["conflict"]) for record in records]

    async def touch(self, conflict_id: str, detected_at: datetime) -> None:
        async with self._client.session() as session:
            await session.run(
                "MATCH (conflict:KnowledgeConflict {id: $id}) SET conflict.last_detected_at = $detected_at",
                id=conflict_id,
                detected_at=detected_at.isoformat(),
            )

    async def auto_clear(self, conflict_id: str, resolved_at: datetime) -> None:
        async with self._client.session() as session:
            await session.run(
                """
                MATCH (conflict:KnowledgeConflict {id: $id, status: 'OPEN'})
                SET conflict.status = 'RESOLVED',
                    conflict.resolved_at = $resolved_at,
                    conflict.resolution_type = 'AUTO_CLEARED'
                """,
                id=conflict_id,
                resolved_at=resolved_at.isoformat(),
            )

    async def count_open(self, namespace: str) -> int:
        async with self._client.session() as session:
            result = await session.run(
                "MATCH (conflict:KnowledgeConflict {namespace: $namespace, status: 'OPEN'}) RETURN count(conflict) AS count",
                namespace=namespace,
            )
            record = await result.single()
        return 0 if record is None else int(record["count"])

    async def resolve_keep_claim(self, conflict_id: str, selected_claim_id: str, reason: str, resolved_at: datetime) -> str:
        source_id = f"human:conflict:{conflict_id}"
        evidence_id = f"human:conflict:evidence:{conflict_id}:{selected_claim_id}"
        async with self._client.session() as session:
            result = await session.execute_write(
                self._resolve_keep_claim_tx,
                conflict_id,
                selected_claim_id,
                reason,
                resolved_at.isoformat(),
                source_id,
                evidence_id,
            )
        return str(result)

    @staticmethod
    async def _resolve_keep_claim_tx(tx: Any, conflict_id: str, selected_claim_id: str, reason: str, resolved_at: str, source_id: str, evidence_id: str) -> str:
        validation = await tx.run(
            """
            MATCH (conflict:KnowledgeConflict {id: $conflict_id})
            OPTIONAL MATCH (conflict)-[:INVOLVES]->(selected:Claim {id: $selected_claim_id})
            RETURN conflict.status AS status, count(selected) AS selected_count
            """,
            conflict_id=conflict_id,
            selected_claim_id=selected_claim_id,
        )
        record = await validation.single()
        if record is None:
            raise ValueError("Conflict does not exist")
        if record["status"] != "OPEN":
            raise RuntimeError("Conflict is already resolved")
        if record["selected_count"] != 1:
            raise ValueError("Selected claim is not involved in this conflict")

        await tx.run(
            """
            MATCH (conflict:KnowledgeConflict {id: $conflict_id})-[:INVOLVES]->(claim:Claim)
            WITH conflict, claim
            SET claim.status = CASE
                    WHEN claim.id = $selected_claim_id THEN 'CONFIRMED'
                    WHEN claim.status = 'CONFIRMED' THEN 'SUPERSEDED'
                    ELSE 'REJECTED'
                END,
                claim.updated_at = $resolved_at
            WITH conflict, claim
            MATCH (selected:Claim {id: $selected_claim_id})
            FOREACH (_ IN CASE WHEN claim.id <> selected.id AND claim.status = 'SUPERSEDED' THEN [1] ELSE [] END |
                MERGE (claim)-[:SUPERSEDED_BY]->(selected)
            )
            """,
            conflict_id=conflict_id,
            selected_claim_id=selected_claim_id,
            resolved_at=resolved_at,
        )
        await ConflictRepository._create_human_resolution_tx(tx, conflict_id, selected_claim_id, reason, resolved_at, source_id, evidence_id)
        await tx.run(
            """
            MATCH (conflict:KnowledgeConflict {id: $conflict_id})
            SET conflict.status = 'RESOLVED',
                conflict.resolved_at = $resolved_at,
                conflict.resolution_type = 'KEEP_CLAIM',
                conflict.selected_claim_id = $selected_claim_id,
                conflict.resolution_reason = $reason
            """,
            conflict_id=conflict_id,
            resolved_at=resolved_at,
            selected_claim_id=selected_claim_id,
            reason=reason,
        )
        return selected_claim_id

    async def resolve_both_valid(self, conflict_id: str, reason: str, resolved_at: datetime) -> None:
        source_id = f"human:conflict:{conflict_id}"
        async with self._client.session() as session:
            await session.execute_write(self._resolve_both_valid_tx, conflict_id, reason, resolved_at.isoformat(), source_id)

    @staticmethod
    async def _resolve_both_valid_tx(tx: Any, conflict_id: str, reason: str, resolved_at: str, source_id: str) -> None:
        validation = await tx.run("MATCH (conflict:KnowledgeConflict {id: $id}) RETURN conflict.status AS status", id=conflict_id)
        record = await validation.single()
        if record is None:
            raise ValueError("Conflict does not exist")
        if record["status"] != "OPEN":
            raise RuntimeError("Conflict is already resolved")
        await tx.run(
            """
            MERGE (source:KnowledgeSource {id: $source_id})
            ON CREATE SET source.source_type = 'HUMAN',
                          source.title = $title,
                          source.external_id = $conflict_id,
                          source.version = 1,
                          source.created_at = $resolved_at
            WITH source
            MATCH (conflict:KnowledgeConflict {id: $conflict_id})
            MERGE (conflict)-[:RESOLVED_BY]->(source)
            SET conflict.status = 'DISMISSED',
                conflict.resolved_at = $resolved_at,
                conflict.resolution_type = 'BOTH_VALID',
                conflict.resolution_reason = $reason
            """,
            source_id=source_id,
            title=f"Human resolution for conflict {conflict_id}",
            conflict_id=conflict_id,
            resolved_at=resolved_at,
            reason=reason,
        )

    async def resolve_corrected(self, conflict_id: str, corrected_claim: Claim, reason: str, resolved_at: datetime) -> str:
        source_id = f"human:conflict:{conflict_id}"
        evidence_id = f"human:conflict:evidence:{conflict_id}:{corrected_claim.id}"
        async with self._client.session() as session:
            result = await session.execute_write(
                self._resolve_corrected_tx,
                conflict_id,
                corrected_claim.model_dump(mode="json"),
                reason,
                resolved_at.isoformat(),
                source_id,
                evidence_id,
            )
        return str(result)

    @staticmethod
    async def _resolve_corrected_tx(tx: Any, conflict_id: str, claim_properties: dict[str, Any], reason: str, resolved_at: str, source_id: str, evidence_id: str) -> str:
        validation = await tx.run("MATCH (conflict:KnowledgeConflict {id: $id}) RETURN conflict.status AS status", id=conflict_id)
        record = await validation.single()
        if record is None:
            raise ValueError("Conflict does not exist")
        if record["status"] != "OPEN":
            raise RuntimeError("Conflict is already resolved")

        await tx.run(
            """
            MATCH (subject:Entity {id: $subject_entity_id})
            MATCH (object:Entity {id: $object_entity_id})
            MERGE (corrected:Claim {id: $claim_id})
            ON CREATE SET corrected = $claim_properties
            SET corrected.status = 'CONFIRMED', corrected.confidence = 1.0, corrected.updated_at = $resolved_at
            MERGE (corrected)-[:SUBJECT]->(subject)
            MERGE (corrected)-[:OBJECT]->(object)
            """,
            subject_entity_id=claim_properties["subject_entity_id"],
            object_entity_id=claim_properties["object_entity_id"],
            claim_id=claim_properties["id"],
            claim_properties=claim_properties,
            resolved_at=resolved_at,
        )
        await tx.run(
            """
            MATCH (conflict:KnowledgeConflict {id: $conflict_id})-[:INVOLVES]->(claim:Claim)
            MATCH (corrected:Claim {id: $corrected_claim_id})
            SET claim.status = CASE
                    WHEN claim.id = corrected.id THEN 'CONFIRMED'
                    WHEN claim.status = 'CONFIRMED' THEN 'SUPERSEDED'
                    ELSE 'REJECTED'
                END,
                claim.updated_at = $resolved_at
            FOREACH (_ IN CASE WHEN claim.id <> corrected.id AND claim.status = 'SUPERSEDED' THEN [1] ELSE [] END |
                MERGE (claim)-[:SUPERSEDED_BY]->(corrected)
            )
            MERGE (conflict)-[:INVOLVES]->(corrected)
            """,
            conflict_id=conflict_id,
            corrected_claim_id=claim_properties["id"],
            resolved_at=resolved_at,
        )
        await ConflictRepository._create_human_resolution_tx(tx, conflict_id, claim_properties["id"], reason, resolved_at, source_id, evidence_id)
        await tx.run(
            """
            MATCH (conflict:KnowledgeConflict {id: $conflict_id})
            SET conflict.status = 'RESOLVED',
                conflict.resolved_at = $resolved_at,
                conflict.resolution_type = 'CORRECTED',
                conflict.selected_claim_id = $corrected_claim_id,
                conflict.resolution_reason = $reason
            """,
            conflict_id=conflict_id,
            resolved_at=resolved_at,
            corrected_claim_id=claim_properties["id"],
            reason=reason,
        )
        return str(claim_properties["id"])

    @staticmethod
    async def _create_human_resolution_tx(tx: Any, conflict_id: str, claim_id: str, reason: str, resolved_at: str, source_id: str, evidence_id: str) -> None:
        await tx.run(
            """
            MATCH (claim:Claim {id: $claim_id})
            MERGE (source:KnowledgeSource {id: $source_id})
            ON CREATE SET source.source_type = 'HUMAN',
                          source.title = $title,
                          source.external_id = $conflict_id,
                          source.version = 1,
                          source.created_at = $resolved_at
            MERGE (evidence:Evidence {id: $evidence_id})
            ON CREATE SET evidence.id = $evidence_id,
                          evidence.claim_id = $claim_id,
                          evidence.source_id = $source_id,
                          evidence.excerpt = $reason,
                          evidence.locator = $locator,
                          evidence.created_at = $resolved_at
            MERGE (claim)-[:SUPPORTED_BY]->(evidence)
            MERGE (evidence)-[:FROM_SOURCE]->(source)
            WITH source
            MATCH (conflict:KnowledgeConflict {id: $conflict_id})
            MERGE (conflict)-[:RESOLVED_BY]->(source)
            """,
            claim_id=claim_id,
            source_id=source_id,
            title=f"Human resolution for conflict {conflict_id}",
            conflict_id=conflict_id,
            evidence_id=evidence_id,
            reason=reason,
            locator=f"Conflict resolution: {conflict_id}",
            resolved_at=resolved_at,
        )

    async def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        async with self._client.session() as session:
            result = await session.run("MATCH (entity:Entity {id: $id}) RETURN entity", id=entity_id)
            record = await result.single()
        return None if record is None else dict(record["entity"])

    async def get_claim(self, claim_id: str) -> Claim | None:
        async with self._client.session() as session:
            result = await session.run("MATCH (claim:Claim {id: $id}) RETURN claim", id=claim_id)
            record = await result.single()
        return None if record is None else Claim(**dict(record["claim"]))
