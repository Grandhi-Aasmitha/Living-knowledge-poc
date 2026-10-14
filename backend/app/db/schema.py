from app.db.neo4j import Neo4jClient


async def ensure_schema(client: Neo4jClient) -> None:
    constraints = [
        "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT claim_id_unique IF NOT EXISTS FOR (n:Claim) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT knowledge_source_id_unique IF NOT EXISTS FOR (n:KnowledgeSource) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT evidence_id_unique IF NOT EXISTS FOR (n:Evidence) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT knowledge_gap_id_unique IF NOT EXISTS FOR (n:KnowledgeGap) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT source_document_id_unique IF NOT EXISTS FOR (n:SourceDocument) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT source_version_id_unique IF NOT EXISTS FOR (n:SourceVersion) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT source_chunk_id_unique IF NOT EXISTS FOR (n:SourceChunk) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT knowledge_conflict_id_unique IF NOT EXISTS FOR (n:KnowledgeConflict) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT learning_batch_id_unique IF NOT EXISTS FOR (n:LearningBatch) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT entity_mention_id_unique IF NOT EXISTS FOR (n:EntityMention) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT alias_binding_id_unique IF NOT EXISTS FOR (n:AliasBinding) REQUIRE n.id IS UNIQUE",
        "CREATE INDEX entity_namespace IF NOT EXISTS FOR (n:Entity) ON (n.namespace)",
        "CREATE INDEX entity_mention_namespace_status IF NOT EXISTS FOR (n:EntityMention) ON (n.namespace, n.status)",
    ]

    async with client.session() as session:
        for constraint in constraints:
            await session.run(constraint)
