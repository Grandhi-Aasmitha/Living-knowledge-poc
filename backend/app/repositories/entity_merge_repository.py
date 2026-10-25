from typing import Any
from uuid import uuid4

from app.db.neo4j import Neo4jClient
from app.domain.entity import Entity
from app.entity_merges import MergeRequest, MergeResult, merge_timestamp, merged_batch_payload, merged_mention_payload
from app.repositories.entity_repository import _entity_from_node


class EntityMergeRepository:
    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    async def merge(self, request: MergeRequest) -> MergeResult:
        if request.keep_id == request.duplicate_id:
            raise ValueError("Choose two different entities")
        async with self._client.session() as session:
            return await session.execute_write(self._merge_in_transaction, request)

    @staticmethod
    async def _merge_in_transaction(tx: Any, request: MergeRequest) -> MergeResult:
        result = await tx.run(
            """
            MATCH (keep:Entity {id: $keep_id, namespace: $namespace, status: 'ACTIVE'})
            MATCH (duplicate:Entity {id: $duplicate_id, namespace: $namespace, status: 'ACTIVE'})
            WHERE keep.entity_type = duplicate.entity_type
            SET keep.lock_revision = coalesce(keep.lock_revision, 0) + 1,
                duplicate.lock_revision = coalesce(duplicate.lock_revision, 0) + 1
            RETURN keep, duplicate
            """,
            keep_id=request.keep_id, duplicate_id=request.duplicate_id, namespace=request.namespace.strip(),
        )
        record = await result.single()
        if record is None:
            raise ValueError("Both entities must still be active in the same namespace and have the same type")
        keep = _entity_from_node(record["keep"])
        duplicate = _entity_from_node(record["duplicate"])
        labels = [duplicate.canonical_name, *duplicate.aliases]
        collision = await tx.run(
            """
            MATCH (other:Entity {namespace: $namespace, entity_type: $entity_type, status: 'ACTIVE'})
            WHERE NOT other.id IN [$keep_id, $duplicate_id]
              AND any(label IN $labels WHERE toLower(other.canonical_name) = toLower(label)
                OR any(alias IN coalesce(other.aliases, []) WHERE toLower(alias) = toLower(label)))
            RETURN other.id AS id LIMIT 1
            """,
            namespace=keep.namespace, entity_type=keep.entity_type,
            keep_id=keep.id, duplicate_id=duplicate.id, labels=labels,
        )
        if await collision.single():
            raise ValueError("A duplicate name also belongs to a third active entity; resolve that identity first")
        relations = await tx.run(
            "MATCH (duplicate:Entity {id: $id})-[relation]-() RETURN collect(DISTINCT type(relation)) AS types",
            id=duplicate.id,
        )
        relation_record = await relations.single()
        unknown = set(relation_record["types"] if relation_record else []) - {"SUBJECT", "OBJECT", "SCOPE", "ABOUT", "RESOLVED_TO", "MERGED_INTO"}
        if unknown:
            raise ValueError("This entity has unsupported graph relationships; merge was cancelled")

        combined_aliases = list(keep.aliases)
        used = {keep.canonical_name.casefold(), *(alias.casefold() for alias in combined_aliases)}
        for label in labels:
            if label.casefold() not in used:
                combined_aliases.append(label)
                used.add(label.casefold())
        timestamp = merge_timestamp()
        updated = await tx.run(
            """
            MATCH (keep:Entity {id: $keep_id}), (duplicate:Entity {id: $duplicate_id})
            SET keep.aliases = $aliases, keep.updated_at = $timestamp,
                duplicate.status = 'RETIRED', duplicate.merged_into_id = keep.id,
                duplicate.updated_at = $timestamp
            MERGE (duplicate)-[:MERGED_INTO]->(keep)
            RETURN keep
            """,
            keep_id=keep.id, duplicate_id=duplicate.id, aliases=combined_aliases, timestamp=timestamp,
        )
        updated_record = await updated.single()
        if updated_record is None:
            raise ValueError("The entity merge could not be saved")

        claim_ids: set[str] = set()
        for role, property_name in (("SUBJECT", "subject_entity_id"), ("OBJECT", "object_entity_id"), ("SCOPE", "scope_entity_id")):
            result = await tx.run(
                f"""
                MATCH (claim:Claim)-[old:{role}]->(duplicate:Entity {{id: $duplicate_id}})
                MATCH (keep:Entity {{id: $keep_id}})
                MERGE (claim)-[:{role}]->(keep)
                DELETE old
                SET claim.{property_name} = $keep_id, claim.updated_at = $timestamp
                RETURN claim.id AS id
                """,
                duplicate_id=duplicate.id, keep_id=keep.id, timestamp=timestamp,
            )
            claim_ids.update(row["id"] for row in await result.data())

        gaps = await tx.run(
            """
            MATCH (gap:KnowledgeGap)-[old:ABOUT]->(duplicate:Entity {id: $duplicate_id})
            MATCH (keep:Entity {id: $keep_id})
            MERGE (gap)-[:ABOUT]->(keep)
            DELETE old
            SET gap.entity_id = $keep_id
            RETURN gap.id AS id
            """,
            duplicate_id=duplicate.id, keep_id=keep.id,
        )
        gap_count = len(await gaps.data())

        mentions = await tx.run(
            "MATCH (mention:EntityMention) WHERE mention.entity_id = $duplicate_id OR mention.payload CONTAINS $duplicate_id RETURN mention.id AS id, mention.payload AS payload",
            duplicate_id=duplicate.id,
        )
        mention_rows = await mentions.data()
        for row in mention_rows:
            payload = merged_mention_payload(row["payload"], duplicate.id, keep.id)
            result = await tx.run(
                """
                MATCH (mention:EntityMention {id: $id}), (keep:Entity {id: $keep_id})
                OPTIONAL MATCH (mention)-[old:RESOLVED_TO]->(duplicate:Entity {id: $duplicate_id})
                FOREACH (relation IN CASE WHEN old IS NULL THEN [] ELSE [old] END | DELETE relation)
                SET mention.payload = $payload,
                    mention.entity_id = CASE WHEN mention.entity_id = $duplicate_id THEN $keep_id ELSE mention.entity_id END
                FOREACH (_ IN CASE WHEN mention.entity_id = $keep_id THEN [1] ELSE [] END | MERGE (mention)-[:RESOLVED_TO]->(keep))
                RETURN mention.id AS id
                """,
                id=row["id"], payload=payload, duplicate_id=duplicate.id, keep_id=keep.id,
            )
            await result.single()

        batches = await tx.run(
            "MATCH (batch:LearningBatch) WHERE batch.payload CONTAINS $duplicate_id RETURN batch.id AS id, batch.payload AS payload",
            duplicate_id=duplicate.id,
        )
        for row in await batches.data():
            result = await tx.run(
                "MATCH (batch:LearningBatch {id: $id}) SET batch.payload = $payload RETURN batch.id AS id",
                id=row["id"], payload=merged_batch_payload(row["payload"], duplicate.id, keep.id),
            )
            await result.single()

        bindings = await tx.run(
            """
            MATCH (binding:AliasBinding)-[old:RESOLVED_TO]->(duplicate:Entity {id: $duplicate_id})
            MATCH (keep:Entity {id: $keep_id})
            MERGE (binding)-[:RESOLVED_TO]->(keep)
            DELETE old
            SET binding.entity_id = $keep_id
            RETURN binding.id AS id
            """,
            duplicate_id=duplicate.id, keep_id=keep.id,
        )
        await bindings.consume()
        review = await tx.run(
            """
            MATCH (keep:Entity {id: $keep_id}), (duplicate:Entity {id: $duplicate_id})
            CREATE (review:EntityMergeReview {id: $id, namespace: $namespace, keep_id: $keep_id,
                duplicate_id: $duplicate_id, reviewer: $reviewer, reason: $reason, created_at: $timestamp})
            MERGE (review)-[:KEPT]->(keep)
            MERGE (review)-[:RETIRED]->(duplicate)
            RETURN review.id AS id
            """,
            id=str(uuid4()), namespace=keep.namespace, keep_id=keep.id, duplicate_id=duplicate.id,
            reviewer=request.reviewer.strip(), reason=request.reason.strip(), timestamp=timestamp,
        )
        if await review.single() is None:
            raise ValueError("The merge review could not be recorded")
        return MergeResult(kept=_entity_from_node(updated_record["keep"]), retired_id=duplicate.id,
                           claims_updated=len(claim_ids), gaps_updated=gap_count, mentions_updated=len(mention_rows))
