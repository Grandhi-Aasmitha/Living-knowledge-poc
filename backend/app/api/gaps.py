from fastapi import APIRouter, Depends, HTTPException

from app.db.neo4j import Neo4jClient, get_neo4j_client
from app.domain.gap import KnowledgeGap
from app.repositories.gap_repository import GapRepository


router = APIRouter(prefix="/api/gaps", tags=["gaps"])


@router.get("", response_model=list[KnowledgeGap])
async def list_open_gaps(client: Neo4jClient = Depends(get_neo4j_client)) -> list[KnowledgeGap]:
    return await GapRepository(client).list_open()


@router.get("/{gap_id}", response_model=KnowledgeGap)
async def get_gap(
    gap_id: str,
    client: Neo4jClient = Depends(get_neo4j_client),
) -> KnowledgeGap:
    gap = await GapRepository(client).get(gap_id)
    if gap is None:
        raise HTTPException(status_code=404, detail="Knowledge gap not found")
    return gap
