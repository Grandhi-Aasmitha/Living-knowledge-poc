from datetime import UTC, datetime
from uuid import uuid4

from app.db.neo4j import Neo4jClient
from app.reviews.models import ClaimReviewRecord, ClaimReviewRequest, PendingClaimReview


class ClaimReviewRepository:
    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    async def list_pending(self, namespace: str) -> list[PendingClaimReview]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (claim:Claim {status: 'PROPOSED'})-[:SUBJECT]->(subject:Entity {namespace: $namespace, status: 'ACTIVE'})
                MATCH (claim)-[:SUPPORTED_BY]->(evidence:Evidence)-[:FROM_SOURCE]->(:KnowledgeSource {source_type: 'FILE_UPLOAD'})
                WHERE coalesce(evidence.is_current, true) AND evidence.excerpt IS NOT NULL
                OPTIONAL MATCH (claim)-[:OBJECT]->(object:Entity)
                WITH claim, subject, object, count(DISTINCT evidence) AS evidence_count
                WHERE object IS NULL OR (object.namespace = $namespace AND object.status = 'ACTIVE')
                RETURN claim.id AS claim_id, subject.canonical_name AS subject_name,
                       claim.predicate AS predicate, object.canonical_name AS object_name,
                       claim.object_value AS object_value, claim.confidence AS confidence,
                       claim.created_at AS created_at, evidence_count
                ORDER BY created_at, claim_id
                LIMIT 100
                """,
                namespace=namespace,
            )
            records = await result.data()
        return [PendingClaimReview(**record) for record in records]

    async def list_history(self, namespace: str) -> list[ClaimReviewRecord]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (claim:Claim)-[:SUBJECT]->(subject:Entity {namespace: $namespace})
                MATCH (claim)-[:HAS_REVIEW]->(review:ClaimReview)
                OPTIONAL MATCH (claim)-[:OBJECT]->(object:Entity)
                RETURN review.id AS id, claim.id AS claim_id, review.namespace AS namespace,
                       subject.canonical_name AS subject_name, claim.predicate AS predicate,
                       object.canonical_name AS object_name, claim.object_value AS object_value,
                       review.decision AS decision, review.reviewer AS reviewer,
                       review.reason AS reason, review.created_at AS created_at
                ORDER BY created_at DESC, id DESC
                LIMIT 100
                """,
                namespace=namespace,
            )
            records = await result.data()
        return [ClaimReviewRecord(**record) for record in records]

    async def review(self, claim_id: str, request: ClaimReviewRequest) -> ClaimReviewRecord | None:
        review_id = str(uuid4())
        reviewed_at = datetime.now(UTC).isoformat()
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (claim:Claim {id: $claim_id})-[:SUBJECT]->(subject:Entity {namespace: $namespace, status: 'ACTIVE'})
                OPTIONAL MATCH (claim)-[:OBJECT]->(object:Entity)
                WITH claim, subject, object
                WHERE (object IS NULL OR (object.namespace = $namespace AND object.status = 'ACTIVE'))
                  AND (
                    (claim.status = 'PROPOSED' AND $decision IN ['CONFIRMED', 'REJECTED'])
                    OR (claim.status IN ['CONFIRMED', 'REJECTED'] AND $decision = 'REOPENED'
                        AND EXISTS { MATCH (claim)-[:HAS_REVIEW]->(:ClaimReview) })
                  )
                  AND EXISTS {
                    MATCH (claim)-[:SUPPORTED_BY]->(evidence:Evidence)-[:FROM_SOURCE]->(:KnowledgeSource {source_type: 'FILE_UPLOAD'})
                    WHERE coalesce(evidence.is_current, true) AND evidence.excerpt IS NOT NULL
                  }
                WITH claim, subject, object, claim.status AS previous_status
                SET claim.status = CASE WHEN $decision = 'REOPENED' THEN 'PROPOSED' ELSE $decision END,
                    claim.confidence = CASE WHEN $decision = 'CONFIRMED' THEN 1.0 ELSE claim.confidence END,
                    claim.updated_at = $reviewed_at
                CREATE (review:ClaimReview {
                    id: $review_id, claim_id: $claim_id, namespace: $namespace,
                    previous_status: previous_status, decision: $decision,
                    reviewer: $reviewer, reason: $reason, created_at: $reviewed_at
                })
                CREATE (claim)-[:HAS_REVIEW]->(review)
                RETURN review.id AS id, claim.id AS claim_id, review.namespace AS namespace,
                       subject.canonical_name AS subject_name, claim.predicate AS predicate,
                       object.canonical_name AS object_name, claim.object_value AS object_value,
                       review.decision AS decision, review.reviewer AS reviewer,
                       review.reason AS reason, review.created_at AS created_at
                """,
                claim_id=claim_id,
                namespace=request.namespace,
                decision=request.decision,
                reviewer=request.reviewer,
                reason=request.reason,
                review_id=review_id,
                reviewed_at=reviewed_at,
            )
            record = await result.single()
        return None if record is None else ClaimReviewRecord(**record.data())
