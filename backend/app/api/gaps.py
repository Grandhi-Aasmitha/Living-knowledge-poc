from fastapi import APIRouter, Depends, Query

from app.completeness.models import GapDetectionResult
from app.completeness.service import GapDetectionService
from app.db.neo4j import Neo4jClient, get_neo4j_client
from app.domain.gap import KnowledgeGap
from app.repositories.completeness_repository import CompletenessRepository
from app.repositories.gap_repository import GapRepository


router = APIRouter(prefix="/api/gaps", tags=["gaps"])


@router.get("", response_model=list[KnowledgeGap])
async def list_open_gaps(
    namespace: str | None = Query(default=None, min_length=1),
    client: Neo4jClient = Depends(get_neo4j_client),
) -> list[KnowledgeGap]:
    return await GapRepository(client).list_open(namespace=namespace.strip() if namespace else None)


@router.post("/detect", response_model=GapDetectionResult)
async def detect_gaps(
    namespace: str = Query(default="tstvs", min_length=1),
    client: Neo4jClient = Depends(get_neo4j_client),
) -> GapDetectionResult:
    gap_repository = GapRepository(client)
    completeness_repository = CompletenessRepository(client)
    return await GapDetectionService(
        completeness_repository=completeness_repository,
        gap_repository=gap_repository,
    ).detect(namespace=namespace.strip())


@router.get("/{gap_id}", response_model=KnowledgeGap)
async def get_gap(
    gap_id: str,
    client: Neo4jClient = Depends(get_neo4j_client),
) -> KnowledgeGap:
    gap = await GapRepository(client).get(gap_id)
    if gap is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Knowledge gap not found")
    return gap
