from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.health import get_neo4j_client
from app.conflicts.models import ConflictDetectionResult, ConflictDetail, ConflictResolutionRequest, ConflictResolutionResult, ConflictSummary
from app.conflicts.service import ConflictDetectionService, ConflictResolutionService, ConflictStateError, ConflictValidationError
from app.db.neo4j import Neo4jClient
from app.domain.enums import ConflictStatus
from app.repositories.claim_repository import ClaimRepository
from app.repositories.conflict_repository import ConflictRepository

router = APIRouter(prefix="/api/conflicts", tags=["conflicts"])


@router.post("/detect", response_model=ConflictDetectionResult)
async def detect_conflicts(
    namespace: str = Query(default="tstvs", min_length=1),
    client: Neo4jClient = Depends(get_neo4j_client),
) -> ConflictDetectionResult:
    return await ConflictDetectionService(ConflictRepository(client)).detect(namespace)


@router.get("", response_model=list[ConflictSummary])
async def list_conflicts(
    namespace: str = Query(default="tstvs", min_length=1),
    status: ConflictStatus | None = Query(default=ConflictStatus.OPEN),
    client: Neo4jClient = Depends(get_neo4j_client),
) -> list[ConflictSummary]:
    return await ConflictRepository(client).list(namespace=namespace, status=status)


@router.get("/{conflict_id}", response_model=ConflictDetail)
async def get_conflict(
    conflict_id: str,
    client: Neo4jClient = Depends(get_neo4j_client),
) -> ConflictDetail:
    conflict = await ConflictRepository(client).get(conflict_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="Conflict not found")
    return conflict


@router.post("/{conflict_id}/resolve", response_model=ConflictResolutionResult)
async def resolve_conflict(
    conflict_id: str,
    request: ConflictResolutionRequest,
    client: Neo4jClient = Depends(get_neo4j_client),
) -> ConflictResolutionResult:
    try:
        return await ConflictResolutionService(ConflictRepository(client), ClaimRepository(client)).resolve(conflict_id, request)
    except ConflictStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ConflictValidationError as error:
        if str(error) == "Conflict does not exist":
            raise HTTPException(status_code=404, detail="Conflict not found") from error
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
