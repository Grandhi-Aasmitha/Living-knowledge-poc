from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.neo4j import Neo4jClient, get_neo4j_client
from app.repositories.claim_review_repository import ClaimReviewRepository
from app.reviews.models import ClaimReviewRecord, ClaimReviewRequest, PendingClaimReview


router = APIRouter(prefix="/api/claim-reviews", tags=["claim reviews"])


def _namespace(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Namespace is required")
    return cleaned


@router.get("", response_model=list[PendingClaimReview])
async def list_pending_claims(
    namespace: str = Query(min_length=1),
    client: Neo4jClient = Depends(get_neo4j_client),
) -> list[PendingClaimReview]:
    return await ClaimReviewRepository(client).list_pending(_namespace(namespace))


@router.get("/history", response_model=list[ClaimReviewRecord])
async def list_claim_reviews(
    namespace: str = Query(min_length=1),
    client: Neo4jClient = Depends(get_neo4j_client),
) -> list[ClaimReviewRecord]:
    return await ClaimReviewRepository(client).list_history(_namespace(namespace))


@router.post("/{claim_id}", response_model=ClaimReviewRecord)
async def review_claim(
    claim_id: str,
    request: ClaimReviewRequest,
    client: Neo4jClient = Depends(get_neo4j_client),
) -> ClaimReviewRecord:
    result = await ClaimReviewRepository(client).review(claim_id, request)
    if result is None:
        raise HTTPException(status_code=409, detail="Claim is not eligible for this decision in the selected namespace")
    return result
