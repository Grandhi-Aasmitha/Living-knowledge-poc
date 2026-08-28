import asyncio
from datetime import UTC, datetime

from app.config import get_settings
from app.db.neo4j import Neo4jClient
from app.db.schema import ensure_schema
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.enums import ClaimStatus, GapPriority, GapStatus, SourceType
from app.domain.evidence import Evidence
from app.domain.gap import KnowledgeGap
from app.domain.source import KnowledgeSource
from app.repositories.claim_repository import ClaimRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.gap_repository import GapRepository
from app.repositories.source_repository import SourceRepository


CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


async def seed() -> dict[str, int]:
    settings = get_settings()
    client = Neo4jClient(
        uri=settings.neo4j_uri,
        username=settings.neo4j_username,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
    )

    try:
        await ensure_schema(client)
        entity_repository = EntityRepository(client)
        source_repository = SourceRepository(client)
        claim_repository = ClaimRepository(client)
        gap_repository = GapRepository(client)

        entities = [
            Entity(
                id="tstvs:team:tstvs",
                entity_type="TEAM",
                canonical_name="TSTVS Team",
                namespace="tstvs",
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            ),
            Entity(
                id="tstvs:service:aggregator",
                entity_type="SERVICE",
                canonical_name="Aggregator Service",
                namespace="tstvs",
                aliases=["Aggregator", "PTR Aggregator"],
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            ),
            Entity(
                id="tstvs:concept:scheduled-dispatch",
                entity_type="BUSINESS_CONCEPT",
                canonical_name="Scheduled Dispatch",
                namespace="tstvs",
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            ),
        ]
        for entity in entities:
            await entity_repository.create(entity)

        source = await source_repository.create(
            KnowledgeSource(
                id="phase2:source:bootstrap",
                source_type=SourceType.SYSTEM,
                title="Phase 2 Bootstrap",
                version="1",
                created_at=CREATED_AT,
            )
        )

        claims = [
            Claim(
                id="phase2:claim:tstvs-owns-aggregator",
                subject_entity_id="tstvs:team:tstvs",
                predicate="OWNS",
                object_entity_id="tstvs:service:aggregator",
                confidence=1.0,
                status=ClaimStatus.CONFIRMED,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            ),
            Claim(
                id="phase2:claim:aggregator-produces-scheduled-dispatch",
                subject_entity_id="tstvs:service:aggregator",
                predicate="PRODUCES",
                object_entity_id="tstvs:concept:scheduled-dispatch",
                confidence=1.0,
                status=ClaimStatus.CONFIRMED,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            ),
        ]
        for claim in claims:
            await claim_repository.create(claim)

        evidence = [
            Evidence(
                id="phase2:evidence:tstvs-owns-aggregator",
                claim_id="phase2:claim:tstvs-owns-aggregator",
                source_id=source.id,
                excerpt="TSTVS Team owns Aggregator Service.",
                created_at=CREATED_AT,
            ),
            Evidence(
                id="phase2:evidence:aggregator-produces-scheduled-dispatch",
                claim_id="phase2:claim:aggregator-produces-scheduled-dispatch",
                source_id=source.id,
                excerpt="Aggregator Service produces Scheduled Dispatch.",
                created_at=CREATED_AT,
            ),
        ]
        for item in evidence:
            await claim_repository.add_evidence(item)

        await gap_repository.create(
            KnowledgeGap(
                id="phase2:gap:scheduled-dispatch-missing-consumer",
                entity_id="tstvs:concept:scheduled-dispatch",
                gap_type="MISSING_CONSUMER",
                description="The consumer of Scheduled Dispatch is currently unknown.",
                priority=GapPriority.HIGH,
                status=GapStatus.OPEN,
                created_at=CREATED_AT,
            )
        )

        return await _summary(client)
    finally:
        await client.close()


async def _summary(client: Neo4jClient) -> dict[str, int]:
    async with client.session() as session:
        result = await session.run(
            """
            MATCH (entity:Entity)
            WHERE entity.id STARTS WITH 'tstvs:'
            WITH count(entity) AS entities
            MATCH (claim:Claim)
            WHERE claim.id STARTS WITH 'phase2:claim:'
            WITH entities, count(claim) AS claims
            MATCH (source:KnowledgeSource)
            WHERE source.id = 'phase2:source:bootstrap'
            WITH entities, claims, count(source) AS sources
            MATCH (evidence:Evidence)
            WHERE evidence.id STARTS WITH 'phase2:evidence:'
            WITH entities, claims, sources, count(evidence) AS evidence
            MATCH (gap:KnowledgeGap {status: 'OPEN'})
            WHERE gap.id = 'phase2:gap:scheduled-dispatch-missing-consumer'
            RETURN entities, claims, sources, evidence, count(gap) AS open_gaps
            """
        )
        record = await result.single()

    if record is None:
        return {"Entities": 0, "Claims": 0, "Sources": 0, "Evidence": 0, "Open gaps": 0}

    return {
        "Entities": record["entities"],
        "Claims": record["claims"],
        "Sources": record["sources"],
        "Evidence": record["evidence"],
        "Open gaps": record["open_gaps"],
    }


def main() -> None:
    summary = asyncio.run(seed())
    for label, count in summary.items():
        print(f"{label}: {count}")


if __name__ == "__main__":
    main()
