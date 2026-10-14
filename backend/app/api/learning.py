from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.neo4j import Neo4jClient, get_neo4j_client
from app.domain.entity import Entity
from app.domain.ontology import validate_entity_type
from app.ai.entity_resolver import _compatible_types
from app.learning.models import ClarificationDetail, ResolveIdentityRequest, ResolveIdentityResponse
from app.learning.service import LearningService
from app.repositories.claim_repository import ClaimRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.learning_repository import LearningRepository


router = APIRouter(prefix="/api/learning", tags=["learning"])


@router.get("/clarifications", response_model=list[ClarificationDetail])
async def list_clarifications(namespace: str = Query(min_length=1), status: Literal["OPEN", "RESOLVED"] = "OPEN", client: Neo4jClient = Depends(get_neo4j_client)):
    return await LearningRepository(client).list_mentions(namespace, status)


@router.get("/entities", response_model=list[Entity])
async def list_candidates(namespace: str = Query(min_length=1), entity_type: str = Query(min_length=1), client: Neo4jClient = Depends(get_neo4j_client)):
    try:
        validate_entity_type(entity_type)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Unknown entity type") from error
    return await EntityRepository(client).list_active_for_resolution(namespace, sorted(_compatible_types(entity_type)))


@router.post("/clarifications/{mention_id}/resolve", response_model=ResolveIdentityResponse)
async def resolve_identity(mention_id: str, request: ResolveIdentityRequest, namespace: str = Query(min_length=1), client: Neo4jClient = Depends(get_neo4j_client)):
    service = LearningService(LearningRepository(client), EntityRepository(client), ClaimRepository(client), DocumentRepository(client))
    try:
        return await service.resolve(mention_id, namespace, request)
    except ValueError as error:
        code = 404 if str(error) == "Clarification not found" else 409
        raise HTTPException(status_code=code, detail=str(error)) from error
