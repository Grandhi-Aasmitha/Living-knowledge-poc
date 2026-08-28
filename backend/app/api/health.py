from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.db.neo4j import Neo4jClient, get_neo4j_client


router = APIRouter(prefix="/api", tags=["health"])


class HealthResponse(BaseModel):
    status: str
    neo4j: str


@router.get("/health", response_model=HealthResponse)
async def health(client: Neo4jClient = Depends(get_neo4j_client)) -> HealthResponse:
    neo4j_is_up = await client.ping()

    if neo4j_is_up:
        return HealthResponse(status="UP", neo4j="UP")

    return HealthResponse(status="DEGRADED", neo4j="DOWN")
