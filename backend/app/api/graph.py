from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.neo4j import Neo4jClient, get_neo4j_client
from app.domain.enums import ClaimStatus
from app.domain.ontology import get_allowed_entity_types, get_allowed_predicates
from app.graph.models import ClaimProvenanceResponse, GraphResponse
from app.repositories.graph_repository import GraphRepository


router = APIRouter(prefix="/api/graph", tags=["graph"])
DEFAULT_CLAIM_STATUSES = [ClaimStatus.CONFIRMED.value, ClaimStatus.PROPOSED.value]


@router.get("/ontology")
async def get_graph_ontology() -> dict[str, list[str]]:
    return {
        "entity_types": sorted(get_allowed_entity_types()),
        "predicates": sorted(get_allowed_predicates()),
    }


def _split_query_values(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    split_values: list[str] = []
    for value in values:
        split_values.extend(part.strip() for part in value.split(","))
    return [value for value in split_values if value]


def _validate_claim_statuses(values: list[str] | None) -> list[str]:
    statuses = _split_query_values(values) or DEFAULT_CLAIM_STATUSES
    allowed = {status.value for status in ClaimStatus}
    invalid = sorted({status for status in statuses if status not in allowed})
    if invalid:
        raise HTTPException(status_code=422, detail=f"Unsupported claim status: {', '.join(invalid)}")
    return statuses


def _validate_entity_types(values: list[str] | None) -> list[str] | None:
    entity_types = _split_query_values(values)
    if not entity_types:
        return None
    allowed = get_allowed_entity_types()
    invalid = sorted({entity_type for entity_type in entity_types if entity_type not in allowed})
    if invalid:
        raise HTTPException(status_code=422, detail=f"Unsupported entity_type: {', '.join(invalid)}")
    return entity_types


@router.get("", response_model=GraphResponse)
async def get_graph(
    namespace: str = "tstvs",
    statuses: list[str] | None = Query(default=None),
    entity_types: list[str] | None = Query(default=None),
    focus_entity_id: str | None = None,
    max_nodes: int = Query(default=200, ge=1, le=500),
    client: Neo4jClient = Depends(get_neo4j_client),
) -> GraphResponse:
    repository = GraphRepository(client)
    return await repository.get_entity_graph(
        namespace=namespace,
        claim_statuses=_validate_claim_statuses(statuses),
        entity_types=_validate_entity_types(entity_types),
        focus_entity_id=focus_entity_id,
        max_nodes=max_nodes,
    )


@router.get("/claims/{claim_id}", response_model=ClaimProvenanceResponse)
async def get_claim_provenance(
    claim_id: str,
    client: Neo4jClient = Depends(get_neo4j_client),
) -> ClaimProvenanceResponse:
    repository = GraphRepository(client)
    provenance = await repository.get_claim_provenance(claim_id)
    if provenance is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return provenance
