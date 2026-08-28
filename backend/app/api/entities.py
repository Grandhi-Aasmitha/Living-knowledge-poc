from fastapi import APIRouter, Depends, HTTPException

from app.db.neo4j import Neo4jClient, get_neo4j_client
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.repositories.claim_repository import ClaimRepository
from app.repositories.entity_repository import EntityRepository


router = APIRouter(prefix="/api/entities", tags=["entities"])


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
