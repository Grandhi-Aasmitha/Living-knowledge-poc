from datetime import UTC, datetime

from app.db.neo4j import Neo4jClient
from app.learning.models import ClarificationDetail, EntityMention, LearningBatch
from app.repositories.entity_repository import EntityRepository


class LearningRepository:
    """Durable observations and pending interpretations, separate from canonical claims."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    async def save_batch(self, batch: LearningBatch) -> LearningBatch:
        async with self._client.session() as session:
            result = await session.run(
                """
                MERGE (batch:LearningBatch {id: $id})
                ON CREATE SET batch.payload = $payload, batch.namespace = $namespace,
                              batch.document_id = $document_id, batch.version_id = $version_id,
                              batch.application_status = 'WAITING'
                WITH batch
                OPTIONAL MATCH (chunk:SourceChunk {id: $chunk_id})
                FOREACH (_ IN CASE WHEN chunk IS NULL THEN [] ELSE [1] END | MERGE (batch)-[:FROM_CHUNK]->(chunk))
                RETURN batch.payload AS payload
                """,
                id=batch.id, payload=batch.model_dump_json(), namespace=batch.namespace,
                document_id=batch.document_id, version_id=batch.version_id, chunk_id=batch.chunk_id,
            )
            record = await result.single()
        return LearningBatch.model_validate_json(record["payload"])

    async def get_batch(self, batch_id: str) -> LearningBatch | None:
        async with self._client.session() as session:
            result = await session.run("MATCH (batch:LearningBatch {id: $id}) RETURN batch.payload AS payload, batch.application_status AS application_status, coalesce(batch.lock_revision, 0) AS revision", id=batch_id)
            record = await result.single()
        if record is None:
            return None
        return LearningBatch.model_validate_json(record["payload"]).model_copy(update={"application_status": record["application_status"], "revision": record["revision"]})

    async def update_batch(self, batch: LearningBatch) -> None:
        async with self._client.session() as session:
            await session.run("MATCH (batch:LearningBatch {id: $id}) SET batch.payload = $payload", id=batch.id, payload=batch.model_dump_json())

    async def get_mention(self, mention_id: str) -> EntityMention | None:
        async with self._client.session() as session:
            result = await session.run("MATCH (mention:EntityMention {id: $id}) RETURN mention.payload AS payload", id=mention_id)
            record = await result.single()
        return None if record is None else EntityMention.model_validate_json(record["payload"])

    async def save_mention(self, mention: EntityMention) -> EntityMention:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (batch:LearningBatch {id: $batch_id})
                MERGE (mention:EntityMention {id: $id})
                ON CREATE SET mention.payload = $payload, mention.namespace = $namespace,
                              mention.status = $status, mention.entity_id = $entity_id
                MERGE (batch)-[:HAS_MENTION]->(mention)
                WITH mention
                OPTIONAL MATCH (entity:Entity {id: $entity_id})
                FOREACH (_ IN CASE WHEN entity IS NULL THEN [] ELSE [1] END | MERGE (mention)-[:RESOLVED_TO]->(entity))
                RETURN mention.payload AS payload
                """,
                batch_id=mention.batch_id, id=mention.id, payload=mention.model_dump_json(),
                namespace=mention.namespace, status=mention.status, entity_id=mention.entity_id,
            )
            record = await result.single()
        if record is None:
            raise ValueError("Learning batch does not exist")
        return EntityMention.model_validate_json(record["payload"])

    async def list_mentions(self, namespace: str, status: str = "OPEN") -> list[ClarificationDetail]:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (batch:LearningBatch {namespace: $namespace})-[:HAS_MENTION]->(mention:EntityMention)
                WHERE mention.status = $status OR ($status = 'OPEN' AND mention.status = 'RESOLVED' AND batch.application_status = 'APPLYING')
                OPTIONAL MATCH (document:SourceDocument {id: batch.document_id})-[:HAS_VERSION]->(version:SourceVersion {id: batch.version_id})
                WITH batch, mention, document, version
                WHERE batch.document_id IS NULL OR (
                    document.latest_version = version.version_number AND coalesce(version.processing_status, 'COMPLETE') = 'COMPLETE'
                )
                RETURN mention.payload AS mention_payload, batch.payload AS batch_payload,
                       batch.application_status AS application_status,
                       document.title AS document_title, version.version_number AS document_version
                ORDER BY mention.id
                """,
                namespace=namespace, status=status,
            )
            rows = await result.data()
        details = []
        for row in rows:
            mention = EntityMention.model_validate_json(row["mention_payload"])
            # Supersession is indexed without rewriting historic interpretation payloads.
            if status == "SUPERSEDED":
                mention = mention.model_copy(update={"status": "SUPERSEDED"})
            batch = LearningBatch.model_validate_json(row["batch_payload"])
            deferred = sum(
                mention.observed.temporary_id in [claim.subject, claim.object_entity, claim.scope_entity]
                for claim in batch.knowledge.claims
            )
            details.append(ClarificationDetail(
                mention=mention, source_title="Human clarification" if batch.chunk_id is None else "Uploaded document",
                document_title=row["document_title"], document_version=row["document_version"],
                locator=batch.locator, excerpt=batch.content[:6000], deferred_claims=deferred,
                application_pending=row["application_status"] == "APPLYING",
            ))
        return details

    async def resolve_mention(self, mention_id: str, namespace: str, entity_id: str, reason: str) -> LearningBatch:
        async def resolve(tx):
            result = await tx.run(
                """
                MATCH (batch:LearningBatch {namespace: $namespace})-[:HAS_MENTION]->(mention:EntityMention {id: $id})
                OPTIONAL MATCH (document:SourceDocument {id: batch.document_id})
                FOREACH (_ IN CASE WHEN document IS NULL THEN [] ELSE [1] END |
                    SET document.lock_revision = coalesce(document.lock_revision, 0) + 1)
                WITH batch, mention, document
                WHERE batch.document_id IS NULL OR document.current_version_id = batch.version_id
                SET batch.lock_revision = coalesce(batch.lock_revision, 0) + 1
                RETURN mention.payload AS mention, mention.status AS status, batch.payload AS batch, batch.lock_revision AS revision
                """,
                id=mention_id, namespace=namespace,
            )
            record = await result.single()
            if record is None:
                raise ValueError("Clarification not found")
            mention = EntityMention.model_validate_json(record["mention"])
            batch = LearningBatch.model_validate_json(record["batch"])
            if record["status"] == "SUPERSEDED":
                raise ValueError("This source version has been superseded")
            if mention.status == "RESOLVED" and mention.entity_id != entity_id:
                raise ValueError("Clarification was already resolved to another entity")
            await EntityRepository.add_alias_in_transaction(tx, entity_id, mention.observed.name, mention.id, reason)
            mention = mention.model_copy(update={
                "status": "RESOLVED", "entity_id": entity_id, "method": "HUMAN",
                "human_reason": mention.human_reason or reason, "resolved_at": mention.resolved_at or datetime.now(UTC),
            })
            batch.bindings[mention.observed.temporary_id] = entity_id
            batch.revision = record["revision"]
            batch.application_status = "APPLYING"
            await tx.run(
                """
                MATCH (mention:EntityMention {id: $id}), (batch:LearningBatch {id: $batch_id}), (entity:Entity {id: $entity_id})
                SET mention.payload = $mention_payload, mention.status = 'RESOLVED', mention.entity_id = $entity_id,
                    batch.payload = $batch_payload, batch.application_status = 'APPLYING'
                MERGE (mention)-[:RESOLVED_TO]->(entity)
                """,
                id=mention_id, batch_id=batch.id, entity_id=entity_id,
                mention_payload=mention.model_dump_json(), batch_payload=batch.model_dump_json(),
            )
            return batch
        async with self._client.session() as session:
            return await session.execute_write(resolve)

    async def mark_materialized(self, batch_id: str, revision: int) -> None:
        async with self._client.session() as session:
            await session.run(
                """
                MATCH (batch:LearningBatch {id: $id})
                SET batch.application_lock = coalesce(batch.application_lock, 0) + 1
                WITH batch
                WHERE coalesce(batch.lock_revision, 0) = $revision
                OPTIONAL MATCH (batch)-[:HAS_MENTION]->(mention:EntityMention {status: 'OPEN'})
                WITH batch, count(mention) AS pending
                SET batch.application_status = CASE WHEN pending = 0 THEN 'APPLIED' ELSE 'WAITING' END
                """, id=batch_id, revision=revision,
            )
