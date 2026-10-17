import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.neo4j import Neo4jClient
from app.repositories.claim_review_repository import ClaimReviewRepository
from app.reviews.models import ClaimReviewRequest


pytestmark = pytest.mark.integration


def test_uploaded_claim_review_lifecycle_rolls_back() -> None:
    async def exercise() -> None:
        settings = Settings()
        client = Neo4jClient(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password, settings.neo4j_database)
        if not await client.ping():
            await client.close()
            pytest.skip("Neo4j is not available")
        namespace = f"test-review-{uuid4().hex[:12]}"
        prefix = f"{namespace}:"
        try:
            async with client.session() as session:
                transaction = await session.begin_transaction()
                try:
                    await transaction.run(
                        """
                        CREATE (subject:Entity {id: $subject_id, namespace: $namespace, status: 'ACTIVE', canonical_name: 'Review Service', entity_type: 'SERVICE'})
                        CREATE (object:Entity {id: $object_id, namespace: $namespace, status: 'ACTIVE', canonical_name: 'Review Database', entity_type: 'DATABASE'})
                        CREATE (claim:Claim {id: $claim_id, subject_entity_id: $subject_id, object_entity_id: $object_id, predicate: 'DEPENDS_ON', status: 'PROPOSED', confidence: 0.7, created_at: $now, updated_at: $now})
                        CREATE (source:KnowledgeSource {id: $source_id, source_type: 'FILE_UPLOAD', title: 'Review test file'})
                        CREATE (evidence:Evidence {id: $evidence_id, claim_id: $claim_id, source_id: $source_id, excerpt: 'Review Service depends on Review Database.', is_current: true})
                        CREATE (claim)-[:SUBJECT]->(subject)
                        CREATE (claim)-[:OBJECT]->(object)
                        CREATE (claim)-[:SUPPORTED_BY]->(evidence)
                        CREATE (evidence)-[:FROM_SOURCE]->(source)
                        """,
                        subject_id=prefix + "subject", object_id=prefix + "object", claim_id=prefix + "claim",
                        source_id=prefix + "source", evidence_id=prefix + "evidence", namespace=namespace,
                        now=datetime.now(UTC).isoformat(),
                    )

                    @asynccontextmanager
                    async def transaction_session():
                        yield transaction

                    class TransactionClient:
                        def session(self):
                            return transaction_session()

                    repository = ClaimReviewRepository(TransactionClient())

                    def decision(value: str) -> ClaimReviewRequest:
                        return ClaimReviewRequest(namespace=namespace, decision=value, reviewer="Test Reviewer", reason="Checked source evidence")

                    assert len(await repository.list_pending(namespace)) == 1
                    assert await repository.review(prefix + "claim", ClaimReviewRequest(namespace="another-team", decision="CONFIRMED", reviewer="Test Reviewer", reason="Wrong team")) is None
                    assert (await repository.review(prefix + "claim", decision("CONFIRMED"))).decision == "CONFIRMED"
                    assert await repository.list_pending(namespace) == []
                    assert await repository.review(prefix + "claim", decision("REJECTED")) is None
                    assert (await repository.review(prefix + "claim", decision("REOPENED"))).decision == "REOPENED"
                    await transaction.run("MATCH (e:Evidence {id: $id}) SET e.is_current = false", id=prefix + "evidence")
                    assert await repository.list_pending(namespace) == []
                    assert await repository.review(prefix + "claim", decision("REJECTED")) is None
                    await transaction.run("MATCH (e:Evidence {id: $id}) SET e.is_current = true", id=prefix + "evidence")
                    assert (await repository.review(prefix + "claim", decision("REJECTED"))).decision == "REJECTED"
                    assert [item.decision for item in await repository.list_history(namespace)] == ["REJECTED", "REOPENED", "CONFIRMED"]
                finally:
                    await transaction.rollback()

            async with client.session() as session:
                result = await session.run("MATCH (claim:Claim {id: $id}) RETURN count(claim) AS count", id=prefix + "claim")
                assert (await result.single())["count"] == 0
        finally:
            await client.close()

    asyncio.run(exercise())
