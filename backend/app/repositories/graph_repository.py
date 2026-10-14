from typing import Any

from app.db.neo4j import Neo4jClient
from app.graph.models import ClaimProvenanceResponse, EvidenceSummary, GraphEdge, GraphNode, GraphResponse


class GraphRepository(Neo4jClient):
    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    async def get_entity_graph(
        self,
        namespace: str,
        claim_statuses: list[str],
        entity_types: list[str] | None = None,
        focus_entity_id: str | None = None,
        max_nodes: int = 200,
    ) -> GraphResponse:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (claim:Claim)-[:SUBJECT]->(subject:Entity)
                MATCH (claim)-[:OBJECT]->(object:Entity)
                WHERE claim.status IN $claim_statuses
                  AND subject.namespace = $namespace
                  AND object.namespace = $namespace
                  AND subject.status = 'ACTIVE'
                  AND object.status = 'ACTIVE'
                  AND (claim.valid_from IS NULL OR datetime(claim.valid_from) <= datetime())
                  AND (claim.valid_to IS NULL OR datetime(claim.valid_to) > datetime())
                  AND (NOT EXISTS { MATCH (claim)-[:SUPPORTED_BY]->(:Evidence) }
                       OR EXISTS { MATCH (claim)-[:SUPPORTED_BY]->(current_evidence:Evidence) WHERE coalesce(current_evidence.is_current, true) })
                  AND ($entity_types IS NULL OR subject.entity_type IN $entity_types OR object.entity_type IN $entity_types)
                  AND ($focus_entity_id IS NULL OR subject.id = $focus_entity_id OR object.id = $focus_entity_id)
                OPTIONAL MATCH (claim)-[:SUPPORTED_BY]->(evidence:Evidence)
                WHERE coalesce(evidence.is_current, true)
                WITH claim, subject, object, count(DISTINCT evidence) AS evidence_count
                ORDER BY claim.created_at, claim.id
                RETURN collect({claim: claim, subject: subject, object: object, evidence_count: evidence_count}) AS rows
                """,
                namespace=namespace,
                claim_statuses=claim_statuses,
                entity_types=entity_types,
                focus_entity_id=focus_entity_id,
            )
            record = await result.single()

        rows: list[dict[str, Any]] = [] if record is None else list(record["rows"])
        nodes_by_id: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []
        truncated = False

        for row in rows:
            subject = row["subject"]
            object_entity = row["object"]
            claim = row["claim"]
            for entity in (subject, object_entity):
                if entity["id"] not in nodes_by_id:
                    if len(nodes_by_id) >= max_nodes:
                        truncated = True
                        break
                    nodes_by_id[entity["id"]] = GraphNode(
                        id=entity["id"],
                        label=entity["canonical_name"],
                        entity_type=entity["entity_type"],
                        namespace=entity["namespace"],
                        status=entity["status"],
                        aliases=entity.get("aliases") or [],
                    )
            if truncated:
                break
            edges.append(
                GraphEdge(
                    id=claim["id"],
                    source=subject["id"],
                    target=object_entity["id"],
                    predicate=claim["predicate"],
                    claim_status=claim["status"],
                    confidence=float(claim["confidence"]),
                    evidence_count=int(row["evidence_count"]),
                )
            )

        return GraphResponse(nodes=list(nodes_by_id.values()), edges=edges, truncated=truncated)

    async def get_claim_provenance(self, claim_id: str) -> ClaimProvenanceResponse | None:
        async with self._client.session() as session:
            result = await session.run(
                """
                MATCH (claim:Claim {id: $claim_id})-[:SUBJECT]->(subject:Entity)
                OPTIONAL MATCH (claim)-[:OBJECT]->(object:Entity)
                OPTIONAL MATCH (claim)-[:SUPPORTED_BY]->(evidence:Evidence)-[:FROM_SOURCE]->(source:KnowledgeSource)
                OPTIONAL MATCH (evidence)-[:FROM_CHUNK]->(chunk:SourceChunk)<-[:HAS_CHUNK]-(version:SourceVersion)<-[:HAS_VERSION]-(document:SourceDocument)
                WITH claim, subject, object, evidence, source, chunk, version, document
                ORDER BY evidence.created_at, evidence.id
                RETURN claim, subject, object,
                       collect(CASE WHEN evidence IS NULL THEN NULL ELSE {
                           evidence: evidence,
                           source: source,
                           chunk: chunk,
                           version: version,
                           document: document
                       } END) AS evidence_rows
                """,
                claim_id=claim_id,
            )
            record = await result.single()

        if record is None:
            return None

        claim = record["claim"]
        subject = record["subject"]
        object_entity = record["object"]
        evidence = []
        for row in record["evidence_rows"]:
            if row is None or row["evidence"] is None or row["source"] is None:
                continue
            evidence_node = row["evidence"]
            source = row["source"]
            document = row["document"]
            version = row["version"]
            chunk = row["chunk"]
            evidence.append(
                EvidenceSummary(
                    id=evidence_node["id"],
                    excerpt=evidence_node.get("excerpt"),
                    locator=evidence_node.get("locator"),
                    source_id=source["id"],
                    source_type=source["source_type"],
                    source_title=source["title"],
                    document_title=None if document is None else document.get("title"),
                    document_version=None if version is None else version.get("version_number"),
                    chunk_locator=None if chunk is None else chunk.get("locator"),
                    is_current=evidence_node.get("is_current", True),
                )
            )

        return ClaimProvenanceResponse(
            claim_id=claim["id"],
            subject_entity_id=subject["id"],
            subject_name=subject["canonical_name"],
            predicate=claim["predicate"],
            object_entity_id=None if object_entity is None else object_entity["id"],
            object_name=None if object_entity is None else object_entity["canonical_name"],
            object_value=claim.get("object_value"),
            status=claim["status"],
            confidence=float(claim["confidence"]),
            evidence=evidence,
        )
