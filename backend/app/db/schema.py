from app.db.neo4j import Neo4jClient


async def ensure_schema(client: Neo4jClient) -> None:
    constraints = [
        "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT claim_id_unique IF NOT EXISTS FOR (n:Claim) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT knowledge_source_id_unique IF NOT EXISTS FOR (n:KnowledgeSource) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT evidence_id_unique IF NOT EXISTS FOR (n:Evidence) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT knowledge_gap_id_unique IF NOT EXISTS FOR (n:KnowledgeGap) REQUIRE n.id IS UNIQUE",
    ]

    async with client.session() as session:
        for constraint in constraints:
            await session.run(constraint)
