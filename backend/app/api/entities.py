from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.neo4j import Neo4jClient, get_neo4j_client
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.entity_merges import DuplicateCandidate, MergeRequest, MergeResult, find_candidates
from app.repositories.claim_repository import ClaimRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.entity_merge_repository import EntityMergeRepository


router = APIRouter(prefix="/api/entities", tags=["entities"])


@router.get("/duplicates", response_model=list[DuplicateCandidate])
async def list_duplicate_candidates(
    namespace: str = Query(min_length=1),
    client: Neo4jClient = Depends(get_neo4j_client),
) -> list[DuplicateCandidate]:
    entities = await EntityRepository(client).list_active_in_namespace(namespace.strip())
    return find_candidates(entities)


@router.get("/active", response_model=list[Entity])
async def list_active_entities(
    namespace: str = Query(min_length=1),
    client: Neo4jClient = Depends(get_neo4j_client),
) -> list[Entity]:
    return await EntityRepository(client).list_active_in_namespace(namespace.strip())


@router.post("/merge", response_model=MergeResult)
async def merge_entities(
    request: MergeRequest,
    client: Neo4jClient = Depends(get_neo4j_client),
) -> MergeResult:
    try:
        return await EntityMergeRepository(client).merge(request)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/{entity_id}", response_model=Entity)
async def get_entity(
    entity_id: str,
    client: Neo4jClient = Depends(get_neo4j_client),
) -> Entity:
    entity = await EntityRepository(client).get(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


@router.get("/{entity_id}/claims", response_model=list[Claim])
async def list_entity_claims(
    entity_id: str,
    client: Neo4jClient = Depends(get_neo4j_client),
) -> list[Claim]:
    return await ClaimRepository(client).list_for_entity(entity_id)
