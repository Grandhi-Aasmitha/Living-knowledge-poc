from typing import Any

from app.assistant.models import (
    EntityResolution,
    MatchedEntity,
    OpenConflictContext,
    OpenGapContext,
    QueryDirection,
    RetrievedClaim,
    RetrievedEvidence,
)
from app.db.neo4j import Neo4jClient


COUNTED_CLAIM_STATUSES = ["CONFIRMED", "PROPOSED"]


class KnowledgeQueryRepository:
    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    async def resolve_entities(self, names: list[str], namespace: str) -> list[EntityResolution]:
        resolutions: list[EntityResolution] = []
        async with self._client.session() as session:
            for name in names:
                result = await session.run(
                    """
                    MATCH (entity:Entity {namespace: $namespace, status: 'ACTIVE'})
                    WHERE toLower(entity.canonical_name) = $name
                       OR any(alias IN coalesce(entity.aliases, []) WHERE toLower(alias) = $name)
                    RETURN entity
                    ORDER BY entity.id
                    """,
                    namespace=namespace,
                    name=name.casefold(),
                )
                records = await result.data()
                resolutions.append(
                    EntityResolution(
                        requested_name=name,
                        matches=[
                            MatchedEntity(
                                id=record["entity"]["id"],
                                label=record["entity"]["canonical_name"],
                                entity_type=record["entity"]["entity_type"],
                                namespace=record["entity"]["namespace"],
                            )
                            for record in records
                        ],
                    )
                )
        return resolutions

    async def get_claim_context(
        self,
        entity_ids: list[str],
        predicates: list[str],
        direction: QueryDirection,
        namespace: str,
        max_claims: int,
        max_evidence_per_claim: int,
        candidate_claim_ids: list[str] | None = None,
    ) -> list[RetrievedClaim]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (claim:Claim)-[:SUBJECT]->(subject:Entity {namespace: $namespace, status: 'ACTIVE'})
                WHERE claim.status IN $claim_statuses
                  AND ($candidate_claim_ids IS NULL OR claim.id IN $candidate_claim_ids)
                  AND ($predicate_count = 0 OR claim.predicate IN $predicates)
                  AND (claim.valid_from IS NULL OR datetime(claim.valid_from) <= datetime())
                  AND (claim.valid_to IS NULL OR datetime(claim.valid_to) > datetime())
                  AND EXISTS { MATCH (claim)-[:SUPPORTED_BY]->(current_evidence:Evidence) WHERE coalesce(current_evidence.is_current, true) }
                OPTIONAL MATCH (claim)-[:OBJECT]->(object:Entity)
                WITH claim, subject, object
                WHERE (
                    $candidate_claim_ids IS NOT NULL
                    OR ($direction = 'OUTGOING' AND subject.id IN $entity_ids)
                    OR ($direction = 'INCOMING' AND object IS NOT NULL AND object.id IN $entity_ids)
                    OR ($direction = 'BOTH' AND (subject.id IN $entity_ids OR (object IS NOT NULL AND object.id IN $entity_ids)))
                  )
                  AND (object IS NULL OR (object.namespace = $namespace AND object.status = 'ACTIVE'))
                OPTIONAL MATCH (claim)-[:SUPPORTED_BY]->(evidence:Evidence)-[:FROM_SOURCE]->(source:KnowledgeSource)
                OPTIONAL MATCH (evidence)-[:FROM_CHUNK]->(chunk:SourceChunk)<-[:HAS_CHUNK]-(version:SourceVersion)<-[:HAS_VERSION]-(document:SourceDocument)
                WITH claim, subject, object, evidence, source, chunk, version, document
                WHERE coalesce(evidence.is_current, true)
                ORDER BY claim.created_at, claim.id, evidence.created_at, evidence.id
                WITH claim, subject, object,
                     collect(CASE WHEN evidence IS NULL THEN NULL ELSE {
                        evidence: evidence,
                        source: source,
                        chunk: chunk,
                        version: version,
                        document: document
                     } END) AS evidence_rows
                RETURN claim, subject, object, [row IN evidence_rows WHERE row IS NOT NULL][..$max_evidence_per_claim] AS evidence_rows
                ORDER BY claim.created_at, claim.id
                LIMIT $max_claims
                """,
                namespace=namespace,
                entity_ids=entity_ids,
                predicates=predicates,
                predicate_count=len(predicates),
                direction=direction.value,
                claim_statuses=COUNTED_CLAIM_STATUSES,
                max_claims=max_claims,
                max_evidence_per_claim=max_evidence_per_claim,
                candidate_claim_ids=candidate_claim_ids,
            )
            records = await result.data()

        return [self._claim_from_record(record) for record in records]

    async def search_service_claim_ids(self, keywords: list[str], namespace: str, max_claims: int) -> list[str]:
        if not keywords:
            return []
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (claim:Claim)-[:SUBJECT]->(subject:Entity {namespace: $namespace, status: 'ACTIVE', entity_type: 'SERVICE'})
                WHERE claim.status IN $claim_statuses
                  AND (claim.valid_from IS NULL OR datetime(claim.valid_from) <= datetime())
                  AND (claim.valid_to IS NULL OR datetime(claim.valid_to) > datetime())
                OPTIONAL MATCH (claim)-[:OBJECT]->(object:Entity)
                WITH claim, subject, object
                WHERE object IS NULL OR (object.namespace = $namespace AND object.status = 'ACTIVE')
                MATCH (claim)-[:SUPPORTED_BY]->(evidence:Evidence)
                WHERE coalesce(evidence.is_current, true)
                  AND any(keyword IN $keywords WHERE
                      toLower(coalesce(evidence.excerpt, '')) CONTAINS keyword
                      OR toLower(subject.canonical_name) CONTAINS keyword
                      OR toLower(coalesce(object.canonical_name, '')) CONTAINS keyword)
                RETURN claim.id AS claim_id, count(DISTINCT evidence) AS evidence_count
                ORDER BY evidence_count DESC, claim_id
                LIMIT $max_claims
                """,
                namespace=namespace,
                claim_statuses=COUNTED_CLAIM_STATUSES,
                keywords=keywords,
                max_claims=max_claims,
            )
            records = await result.data()
        return [record["claim_id"] for record in records]

    async def get_open_gaps(self, entity_ids: list[str]) -> list[OpenGapContext]:
        if not entity_ids:
            return []
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (gap:KnowledgeGap {status: 'OPEN'})-[:ABOUT]->(entity:Entity)
                WHERE entity.id IN $entity_ids
                RETURN gap
                ORDER BY gap.priority, gap.created_at, gap.id
                """,
                entity_ids=entity_ids,
            )
            records = await result.data()
        return [
            OpenGapContext(
                id=record["gap"]["id"],
                entity_id=record["gap"]["entity_id"],
                gap_type=record["gap"]["gap_type"],
                description=record["gap"]["description"],
                priority=record["gap"]["priority"],
            )
            for record in records
        ]

    async def get_open_conflicts(self, claim_ids: list[str]) -> list[OpenConflictContext]:
        if not claim_ids:
            return []
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (conflict:KnowledgeConflict {status: 'OPEN'})-[:INVOLVES]->(claim:Claim)
                WHERE claim.id IN $claim_ids
                WITH DISTINCT conflict
                MATCH (conflict)-[:INVOLVES]->(involved:Claim)
                RETURN conflict, collect(DISTINCT involved.id) AS claim_ids
                ORDER BY conflict.created_at, conflict.id
                """,
                claim_ids=claim_ids,
            )
            records = await result.data()
        return [
            OpenConflictContext(
                id=record["conflict"]["id"],
                rule_id=record["conflict"]["rule_id"],
                description=record["conflict"]["description"],
                claim_ids=sorted(record["claim_ids"]),
            )
            for record in records
        ]

    def _claim_from_record(self, record: dict[str, Any]) -> RetrievedClaim:
        claim = record["claim"]
        subject = record["subject"]
        object_entity = record["object"]
        return RetrievedClaim(
            claim_id=claim["id"],
            subject_entity_id=subject["id"],
            subject_name=subject["canonical_name"],
            subject_type=subject["entity_type"],
            predicate=claim["predicate"],
            object_entity_id=None if object_entity is None else object_entity["id"],
            object_name=None if object_entity is None else object_entity["canonical_name"],
            object_value=claim.get("object_value"),
            claim_status=claim["status"],
            confidence=float(claim["confidence"]),
            evidence=[self._evidence_from_row(row) for row in record["evidence_rows"] if row.get("evidence") is not None and row.get("source") is not None],
        )

    def _evidence_from_row(self, row: dict[str, Any]) -> RetrievedEvidence:
        evidence = row["evidence"]
        source = row["source"]
        document = row.get("document")
        version = row.get("version")
        return RetrievedEvidence(
            evidence_id=evidence["id"],
            source_id=source["id"],
            source_type=source["source_type"],
            source_title=source["title"],
            excerpt=evidence.get("excerpt"),
            locator=evidence.get("locator"),
            document_title=None if document is None else document.get("title"),
            document_version=None if version is None else version.get("version_number"),
            source_url=source.get("source_url"),
        )
