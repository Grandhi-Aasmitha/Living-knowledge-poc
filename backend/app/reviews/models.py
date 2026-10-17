from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


ReviewDecision = Literal["CONFIRMED", "REJECTED", "REOPENED"]


class ClaimReviewRequest(BaseModel):
    namespace: str = Field(max_length=120)
    decision: ReviewDecision
    reviewer: str = Field(max_length=120)
    reason: str = Field(max_length=1000)

    @field_validator("namespace", "reviewer", "reason")
    @classmethod
    def text_must_be_meaningful(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A namespace, reviewer name, and reason are required")
        return cleaned


class PendingClaimReview(BaseModel):
    claim_id: str
    subject_name: str
    predicate: str
    object_name: str | None
    object_value: str | None
    confidence: float
    created_at: datetime
    evidence_count: int


class ClaimReviewRecord(BaseModel):
    id: str
    claim_id: str
    namespace: str
    subject_name: str
    predicate: str
    object_name: str | None
    object_value: str | None
    decision: ReviewDecision
    reviewer: str
    reason: str
    created_at: datetime
