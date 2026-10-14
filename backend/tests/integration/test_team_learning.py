import asyncio
from collections import deque
from pathlib import Path
from uuid import uuid4

import pytest

from app.ai.client import AIProviderError
from app.ai.entity_resolution_models import EntityResolutionDecision
from app.ai.extraction_models import ExtractedKnowledge
from app.assistant.models import QueryDirection
from app.config import get_settings
from app.db.neo4j import Neo4jClient
from app.db.schema import ensure_schema
from app.domain.entity import Entity
from app.learning.models import ResolveIdentityRequest
from app.learning.service import LearningService
from app.repositories.claim_repository import ClaimRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.knowledge_query_repository import KnowledgeQueryRepository
from app.repositories.learning_repository import LearningRepository
from app.repositories.source_repository import SourceRepository
from app.services.file_ingestion_service import FileIngestionService
from app.ai.entity_resolver import EntityResolver
from app.domain.gap import KnowledgeGap
from app.repositories.gap_repository import GapRepository
from app.workflows.curation import CurationWorkflow


pytestmark = pytest.mark.integration
CONTENT = b"TSTVS handles dispatch."


def extraction(name="TSTVS", aliases=None, claims=True):
    return {
        "entities": [{"temporary_id": "system", "entity_type": "SYSTEM", "name": name, "aliases": aliases or []}],
        "claims": [{"subject": "system", "predicate": "PURPOSE", "object_value": "dispatch", "confidence": 0.95, "evidence_text": "TSTVS handles dispatch."}] if claims else [],
    }


class ScriptedAI:
    def __init__(self, extractions, decisions):
        self.extractions = deque(extractions)
        self.decisions = deque(decisions)
        self.extraction_calls = 0
        self.resolution_calls = 0

    async def generate_structured(self, prompt, response_model):
        if response_model is ExtractedKnowledge:
            self.extraction_calls += 1
            return response_model(**self.extractions.popleft())
        assert response_model is EntityResolutionDecision
        self.resolution_calls += 1
        decision = self.decisions.popleft()
        if decision is None:
            raise AIProviderError("simulated resolution failure")
        return response_model(**decision)


async def setup(tmp_path: Path):
    settings = get_settings()
    client = Neo4jClient(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password, settings.neo4j_database)
    if not await client.ping():
        await client.close()
        pytest.skip("Neo4j is not available")
    await ensure_schema(client)
    namespace = f"learning-eval-{uuid4().hex[:12]}"
    entities = EntityRepository(client)
    system = await entities.create(Entity(id=f"{namespace}:system:canonical", entity_type="SYSTEM", canonical_name="TSTVS System", namespace=namespace))
    return client, namespace, system


def ingestion(client, tmp_path, ai):
    return FileIngestionService(
        ai, SourceRepository(client), DocumentRepository(client), EntityRepository(client), ClaimRepository(client),
        str(tmp_path / "uploads"), 10, 6000, 20, learning_repository=LearningRepository(client),
    )


def learning(client):
    return LearningService(LearningRepository(client), EntityRepository(client), ClaimRepository(client), DocumentRepository(client))


async def cleanup(client, namespace):
    async with client.session() as session:
        # Only remove this fixture's namespace and its document versions/evidence.
        for query in [
            "MATCH (n:KnowledgeGap)-[:ABOUT]->(:Entity {namespace: $namespace}) DETACH DELETE n",
            "MATCH (n:KnowledgeSource) WHERE n.external_id STARTS WITH $namespace DETACH DELETE n",
            "MATCH (n:AliasBinding)-[:RESOLVED_TO]->(:Entity {namespace: $namespace}) DETACH DELETE n",
            "MATCH (n:EntityMention {namespace: $namespace}) DETACH DELETE n",
            "MATCH (n:LearningBatch {namespace: $namespace}) DETACH DELETE n",
            "MATCH (c:Claim)-[:SUBJECT]->(:Entity {namespace: $namespace}) OPTIONAL MATCH (c)-[:SUPPORTED_BY]->(e:Evidence) DETACH DELETE c, e",
            "MATCH (d:SourceDocument {namespace: $namespace}) OPTIONAL MATCH (d)-[:HAS_VERSION]->(v:SourceVersion) OPTIONAL MATCH (v)-[:HAS_CHUNK]->(c:SourceChunk) DETACH DELETE d, v, c",
            "MATCH (n:Entity {namespace: $namespace}) DETACH DELETE n",
        ]:
            await session.run(query, namespace=namespace)
    await client.close()


def test_uncertainty_survives_reload_human_resolution_and_later_upload(tmp_path):
    async def scenario():
        client, namespace, system = await setup(tmp_path)
        try:
            ai = ScriptedAI([extraction()], [{"action": "NEEDS_REVIEW", "confidence": 0.6, "reason": "The acronym needs confirmation"}])
            first = await ingestion(client, tmp_path, ai).ingest(CONTENT, "architecture.md", namespace)
            assert first.claims_created == 0
            questions = await learning(client).repository.list_mentions(namespace)
            assert len(questions) == 1
            assert questions[0].deferred_claims == 1
            assert questions[0].excerpt == CONTENT.decode()
            # A new service instance represents a backend restart / subsequent session.
            retry = await ingestion(client, tmp_path, ScriptedAI([], [])).ingest(CONTENT, "architecture.md", namespace)
            assert retry.status == "UNCHANGED"
            assert len(await learning(client).repository.list_mentions(namespace)) == 1
            decision = ResolveIdentityRequest(decision="MATCH", entity_id=system.id, reason="TSTVS is our abbreviated system name")
            result = await learning(client).resolve(questions[0].mention.id, namespace, decision)
            assert result.claims_applied == 1
            assert result.pending_mentions == 0
            assert await learning(client).repository.list_mentions(namespace) == []
            history = await learning(client).repository.list_mentions(namespace, "RESOLVED")
            assert history[0].mention.human_reason == decision.reason
            assert "TSTVS" in (await EntityRepository(client).get(system.id)).aliases
            await learning(client).resolve(questions[0].mention.id, namespace, decision)
            async with client.session() as session:
                row = await (await session.run("MATCH (c:Claim)-[:SUBJECT]->(:Entity {id: $id}) OPTIONAL MATCH (c)-[:SUPPORTED_BY]->(e:Evidence) RETURN count(DISTINCT c) AS claims, count(DISTINCT e) AS evidence", id=system.id)).single()
            assert row["claims"] == row["evidence"] == 1
            later_ai = ScriptedAI([extraction()], [])
            later = await ingestion(client, tmp_path, later_ai).ingest(CONTENT, "runbook.md", namespace)
            assert later.entities_created == 0
            assert later_ai.resolution_calls == 0
            forced = await ingestion(client, tmp_path, ScriptedAI([extraction()], [])).ingest(CONTENT, "runbook.md", namespace, force=True)
            assert forced.status == "INGESTED"
            assert forced.version_id != later.version_id
            resolved = await KnowledgeQueryRepository(client).resolve_entities(["TSTVS"], namespace)
            assert resolved[0].matches[0].id == system.id
            claims = await KnowledgeQueryRepository(client).get_claim_context([system.id], ["PURPOSE"], QueryDirection.OUTGOING, namespace, 25, 2)
            assert len(claims) == 1
            assert claims[0].claim_status == "PROPOSED"
        finally:
            await cleanup(client, namespace)
    asyncio.run(scenario())


def test_resolution_failure_retries_saved_proposals_without_false_unchanged(tmp_path):
    async def scenario():
        client, namespace, system = await setup(tmp_path)
        try:
            ai = ScriptedAI([extraction()], [None, {"action": "MATCH", "matched_entity_id": system.id, "confidence": 0.98, "reason": "Same system"}])
            service = ingestion(client, tmp_path, ai)
            with pytest.raises(AIProviderError):
                await service.ingest(CONTENT, "retry.md", namespace)
            documents = await DocumentRepository(client).list_documents()
            document = next(doc for doc in documents if doc.namespace == namespace)
            assert document.latest_version == 0
            assert document.current_content_hash == ""
            result = await service.ingest(CONTENT, "retry.md", namespace)
            assert result.status == "INGESTED"
            assert ai.extraction_calls == 1
            assert len(await ClaimRepository(client).list_for_entity(system.id)) == 1
        finally:
            await cleanup(client, namespace)
    asyncio.run(scenario())


def test_document_updates_deactivate_old_evidence_and_supersede_questions(tmp_path):
    async def scenario():
        client, namespace, system = await setup(tmp_path)
        try:
            ai = ScriptedAI([extraction(), extraction(claims=False)], [{"action": "MATCH", "matched_entity_id": system.id, "confidence": 0.98, "reason": "Same system"}])
            service = ingestion(client, tmp_path, ai)
            first = await service.ingest(CONTENT, "changing.md", namespace)
            await service.ingest(b"TSTVS now handles something else.", "changing.md", namespace)
            claims = await KnowledgeQueryRepository(client).get_claim_context([system.id], [], QueryDirection.BOTH, namespace, 25, 2)
            assert claims == []
            async with client.session() as session:
                row = await (await session.run("MATCH (:SourceVersion {id: $id})-[:HAS_CHUNK]->(:SourceChunk)<-[:FROM_CHUNK]-(e:Evidence) RETURN e.is_current AS current", id=first.version_id)).single()
            assert row["current"] is False
            # Historic canonical claims remain stored for provenance inspection.
            assert len(await ClaimRepository(client).list_for_entity(system.id)) == 1
            other_ai = ScriptedAI([extraction(name="Tactical STVS"), extraction(claims=False)], [{"action": "NEEDS_REVIEW", "confidence": 0.5, "reason": "Uncertain"}])
            other = ingestion(client, tmp_path, other_ai)
            await other.ingest(CONTENT, "questions.md", namespace)
            question = (await learning(client).repository.list_mentions(namespace))[0]
            await other.ingest(b"Source no longer describes dispatch.", "questions.md", namespace)
            assert not any(item.mention.id == question.mention.id for item in await learning(client).repository.list_mentions(namespace))
            with pytest.raises(ValueError, match="not current"):
                await learning(client).resolve(question.mention.id, namespace, ResolveIdentityRequest(decision="MATCH", entity_id=system.id, reason="Old source"))
        finally:
            await cleanup(client, namespace)
    asyncio.run(scenario())


def test_same_filename_is_independent_in_two_namespaces(tmp_path):
    async def scenario():
        client, namespace, system = await setup(tmp_path)
        other_namespace = namespace + "-other"
        try:
            first_ai = ScriptedAI([extraction()], [{"action": "MATCH", "matched_entity_id": system.id, "confidence": 0.98, "reason": "Same system"}])
            first = await ingestion(client, tmp_path, first_ai).ingest(CONTENT, "same.md", namespace)
            second = await ingestion(client, tmp_path, ScriptedAI([extraction()], [])).ingest(CONTENT, "same.md", other_namespace)
            assert second.status == "INGESTED"
            assert first.document_id != second.document_id
            assert first.version_id != second.version_id
            assert second.entities_created == 1
        finally:
            # Cleanup closes a client, so remove the other namespace using its own driver.
            settings = get_settings()
            other_client = Neo4jClient(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password, settings.neo4j_database)
            await cleanup(other_client, other_namespace)
            await cleanup(client, namespace)
    asyncio.run(scenario())


def test_known_entity_after_first_200_and_explicit_alias_are_reused(tmp_path):
    async def scenario():
        client, namespace, system = await setup(tmp_path)
        try:
            entities = EntityRepository(client)
            # These names sort before the target: the former limit lost this known entity.
            async with client.session() as session:
                await session.run("UNWIND range(0, 224) AS i CREATE (:Entity {id: $namespace + ':filler:' + toString(i), canonical_name: 'Alpha ' + toString(i), entity_type: 'SYSTEM', namespace: $namespace, status: 'ACTIVE', created_at: $now, updated_at: $now})", namespace=namespace, now=system.created_at.isoformat())
            await entities.add_alias(system.id, "TSTVS")
            exact_ai = ScriptedAI([extraction()], [])
            result = await ingestion(client, tmp_path, exact_ai).ingest(CONTENT, "known.md", namespace)
            assert result.entities_created == 0
            assert exact_ai.resolution_calls == 0
            alias_ai = ScriptedAI([extraction(name="Aurora", aliases=["TSTVS System"])], [{"action": "MATCH", "matched_entity_id": system.id, "confidence": 0.98, "reason": "Explicit alternate name"}])
            result = await ingestion(client, tmp_path, alias_ai).ingest(b"Aurora is TSTVS System. TSTVS handles dispatch.", "aliases.md", namespace)
            assert result.entities_created == 0
            assert "Aurora" in (await entities.get(system.id)).aliases
        finally:
            await cleanup(client, namespace)
    asyncio.run(scenario())


def test_concurrent_clarifications_preserve_both_bindings(tmp_path):
    async def scenario():
        client, namespace, system = await setup(tmp_path)
        try:
            entities = EntityRepository(client)
            orders = await entities.create(Entity(id=namespace+":orders", entity_type="SYSTEM", canonical_name="Orders System", namespace=namespace))
            billing = await entities.create(Entity(id=namespace+":billing", entity_type="SYSTEM", canonical_name="Billing System", namespace=namespace))
            payload = {"entities": [{"temporary_id": "orders", "name": "Orders", "entity_type": "SYSTEM"}, {"temporary_id": "billing", "name": "Billing", "entity_type": "SYSTEM"}], "claims": [{"subject": "orders", "predicate": "CALLS", "object_entity": "billing", "confidence": 0.9, "evidence_text": "Orders calls Billing."}]}
            ai = ScriptedAI([payload], [{"action": "NEEDS_REVIEW", "confidence": 0.5, "reason": "Confirm identity"}] * 2)
            await ingestion(client, tmp_path, ai).ingest(b"Orders calls Billing.", "concurrent.md", namespace)
            questions = await learning(client).repository.list_mentions(namespace)
            targets = {"Orders": orders.id, "Billing": billing.id}
            await asyncio.gather(*[learning(client).resolve(question.mention.id, namespace, ResolveIdentityRequest(decision="MATCH", entity_id=targets[question.mention.observed.name], reason="Team confirms identity")) for question in questions])
            batch = await learning(client).repository.get_batch(questions[0].mention.batch_id)
            assert batch.bindings == {"orders": orders.id, "billing": billing.id}
            assert await learning(client).repository.list_mentions(namespace) == []
            claims = await KnowledgeQueryRepository(client).get_claim_context([orders.id], ["CALLS"], QueryDirection.OUTGOING, namespace, 25, 2)
            assert len(claims) == 1
            assert claims[0].object_entity_id == billing.id
        finally:
            await cleanup(client, namespace)
    asyncio.run(scenario())


def test_failed_materialization_remains_in_queue_and_can_be_retried(tmp_path):
    async def scenario():
        client, namespace, system = await setup(tmp_path)
        try:
            await ingestion(client, tmp_path, ScriptedAI([extraction()], [{"action": "NEEDS_REVIEW", "confidence": 0.5, "reason": "Confirm name"}])).ingest(CONTENT, "deferred.md", namespace)
            service = learning(client)
            question = (await service.repository.list_mentions(namespace))[0]
            original = service.claims.add_evidence
            async def fail_once(evidence):
                raise RuntimeError("simulated storage failure")
            service.claims.add_evidence = fail_once
            request = ResolveIdentityRequest(decision="MATCH", entity_id=system.id, reason="Same application")
            with pytest.raises(RuntimeError):
                await service.resolve(question.mention.id, namespace, request)
            pending = await service.repository.list_mentions(namespace)
            assert len(pending) == 1
            assert pending[0].application_pending
            service.claims.add_evidence = original
            await service.resolve(question.mention.id, namespace, request)
            assert await service.repository.list_mentions(namespace) == []
        finally:
            await cleanup(client, namespace)
    asyncio.run(scenario())


def test_ambiguous_curation_identity_uses_saved_queue_and_resolves_original_gap(tmp_path):
    async def scenario():
        client, namespace, system = await setup(tmp_path)
        try:
            entities = EntityRepository(client)
            topic = await entities.create(Entity(id=namespace+":topic", entity_type="TOPIC", canonical_name="Dispatch Topic", namespace=namespace))
            gap = await GapRepository(client).create(KnowledgeGap(id=namespace+":gap", entity_id=topic.id, gap_type="MISSING_CONSUMER", description="Unknown consumer", priority="HIGH"))
            ai = ScriptedAI([], [{"action": "NEEDS_REVIEW", "confidence": 0.5, "reason": "Confirm which system is intended"}])
            workflow = CurationWorkflow(entities, ClaimRepository(client), SourceRepository(client), GapRepository(client), None, None, None, EntityResolver(ai, entities), LearningRepository(client))
            state = {
                "workflow_id": namespace+":workflow", "gap_id": gap.id, "namespace": namespace,
                "question": "Which system consumes Dispatch Topic?", "engineer_answer": "Tactical STVS",
                "interpretation": {"can_resolve": True, "entity_name": "Tactical STVS", "entity_type": "SYSTEM"},
                "claim_candidate": {"subject_entity_id": namespace+":candidate", "predicate": "CONSUMES", "object_entity_id": topic.id, "confidence": 1.0},
                "_entity": topic.model_dump(mode="json"),
            }
            result = await workflow.persist_knowledge_for_retry(state)
            assert result["status"] == "NEEDS_REVIEW"
            questions = await learning(client).repository.list_mentions(namespace)
            assert len(questions) == 1
            await learning(client).resolve(questions[0].mention.id, namespace, ResolveIdentityRequest(decision="MATCH", entity_id=system.id, reason="Our system's alternate name"))
            assert (await GapRepository(client).get(gap.id)).status == "RESOLVED"
            claims = await ClaimRepository(client).list_for_entity(system.id)
            assert len(claims) == 1
            assert claims[0].status == "CONFIRMED"
            # Retrying the original workflow reuses the recovered canonical claim.
            await workflow.persist_knowledge_for_retry(state)
            assert len(await ClaimRepository(client).list_for_entity(system.id)) == 1
        finally:
            await cleanup(client, namespace)
    asyncio.run(scenario())
