import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.ai.extraction_models import ExtractedEntity, ExtractedKnowledge
from app.config import Settings
from app.db.neo4j import Neo4jClient
from app.entity_merges import MergeRequest
from app.learning.models import EntityMention, LearningBatch
from app.repositories.entity_merge_repository import EntityMergeRepository


pytestmark = pytest.mark.integration


def test_approved_merge_reconnects_claims_and_retains_evidence() -> None:
    async def exercise() -> None:
        settings = Settings()
        client = Neo4jClient(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password, settings.neo4j_database)
        if not await client.ping():
            await client.close()
            pytest.skip("Neo4j is not available")
        namespace = f"merge-test-{uuid4().hex[:12]}"
        observed = ExtractedEntity(temporary_id="service", name="Aster Track Service", entity_type="SERVICE")
        mention_payload = EntityMention(id=namespace + ":mention", batch_id=namespace + ":batch", namespace=namespace,
                                        observed=observed, status="RESOLVED", entity_id=namespace + ":duplicate").model_dump_json()
        batch_payload = LearningBatch(id=namespace + ":batch", namespace=namespace, source_id=namespace + ":source",
                                      content="Aster Track Service publishes to Shipment Topic.",
                                      knowledge=ExtractedKnowledge(entities=[observed], claims=[]),
                                      bindings={"service": namespace + ":duplicate"}).model_dump_json()
        try:
            async with client.session() as session:
                transaction = await session.begin_transaction()
                try:
                    seed = await transaction.run(
                        """
                        CREATE (keep:Entity {id: $keep_id, namespace: $namespace, status: 'ACTIVE', canonical_name: 'Aster Tracking Service', entity_type: 'SERVICE', aliases: []})
                        CREATE (duplicate:Entity {id: $duplicate_id, namespace: $namespace, status: 'ACTIVE', canonical_name: 'Aster Track Service', entity_type: 'SERVICE', aliases: []})
                        CREATE (target:Entity {id: $target_id, namespace: $namespace, status: 'ACTIVE', canonical_name: 'Shipment Topic', entity_type: 'TOPIC', aliases: []})
                        CREATE (claim:Claim {id: $claim_id, subject_entity_id: $duplicate_id, object_entity_id: $target_id, predicate: 'PUBLISHES_TO', status: 'CONFIRMED', confidence: 0.8, created_at: $now, updated_at: $now})
                        CREATE (evidence:Evidence {id: $evidence_id, claim_id: $claim_id, excerpt: 'Aster Track Service publishes to Shipment Topic.', is_current: true})
                        CREATE (gap:KnowledgeGap {id: $gap_id, entity_id: $duplicate_id, gap_type: 'MISSING_OWNER', status: 'OPEN'})
                        CREATE (mention:EntityMention {id: $mention_id, namespace: $namespace, entity_id: $duplicate_id, payload: $mention_payload})
                        CREATE (batch:LearningBatch {id: $batch_id, namespace: $namespace, payload: $batch_payload})
                        CREATE (claim)-[:SUBJECT]->(duplicate)
                        CREATE (claim)-[:OBJECT]->(target)
                        CREATE (claim)-[:SUPPORTED_BY]->(evidence)
                        CREATE (gap)-[:ABOUT]->(duplicate)
                        CREATE (mention)-[:RESOLVED_TO]->(duplicate)
                        CREATE (batch)-[:HAS_MENTION]->(mention)
                        RETURN claim.id AS id
                        """,
                        namespace=namespace, keep_id=namespace + ":keep", duplicate_id=namespace + ":duplicate",
                        target_id=namespace + ":target", claim_id=namespace + ":claim", evidence_id=namespace + ":evidence",
                        gap_id=namespace + ":gap", now=datetime.now(UTC).isoformat(),
                        mention_id=namespace + ":mention", batch_id=namespace + ":batch",
                        mention_payload=mention_payload, batch_payload=batch_payload,
                    )
                    assert await seed.single()
                    request = MergeRequest(namespace=namespace, keep_id=namespace + ":keep",
                                           duplicate_id=namespace + ":duplicate", reviewer="Tester", reason="Same service")
                    result = await EntityMergeRepository._merge_in_transaction(transaction, request)
                    assert result.claims_updated == 1
                    assert result.gaps_updated == 1
                    assert result.mentions_updated == 1
                    assert "Aster Track Service" in result.kept.aliases
                    check = await transaction.run(
                        """
                        MATCH (claim:Claim {id: $claim_id})-[:SUBJECT]->(keep:Entity {id: $keep_id})
                        MATCH (claim)-[:SUPPORTED_BY]->(evidence:Evidence {id: $evidence_id})
                        MATCH (gap:KnowledgeGap {id: $gap_id})-[:ABOUT]->(keep)
                        MATCH (duplicate:Entity {id: $duplicate_id, status: 'RETIRED'})-[:MERGED_INTO]->(keep)
                        MATCH (review:EntityMergeReview {keep_id: $keep_id, duplicate_id: $duplicate_id})
                        MATCH (mention:EntityMention {id: $mention_id})-[:RESOLVED_TO]->(keep)
                        MATCH (batch:LearningBatch {id: $batch_id})
                        RETURN claim.subject_entity_id AS claim_subject, gap.entity_id AS gap_entity,
                               evidence.excerpt AS excerpt, review.reviewer AS reviewer,
                               mention.payload AS mention_payload, batch.payload AS batch_payload
                        """,
                        claim_id=namespace + ":claim", keep_id=request.keep_id,
                        duplicate_id=request.duplicate_id, evidence_id=namespace + ":evidence", gap_id=namespace + ":gap",
                        mention_id=namespace + ":mention", batch_id=namespace + ":batch",
                    )
                    row = await check.single()
                    assert row is not None
                    assert row["claim_subject"] == request.keep_id
                    assert row["gap_entity"] == request.keep_id
                    assert row["reviewer"] == "Tester"
                    assert "publishes" in row["excerpt"]
                    assert EntityMention.model_validate_json(row["mention_payload"]).entity_id == request.keep_id
                    assert LearningBatch.model_validate_json(row["batch_payload"]).bindings["service"] == request.keep_id
                    with pytest.raises(ValueError):
                        await EntityMergeRepository._merge_in_transaction(transaction, request)
                finally:
                    await transaction.rollback()
        finally:
            await client.close()

    asyncio.run(exercise())
