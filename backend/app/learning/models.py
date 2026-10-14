from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.ai.entity_resolution_models import EntityResolutionCandidate
from app.ai.extraction_models import ExtractedEntity, ExtractedKnowledge
from app.domain.validation import NonBlankString


class EntityMention(BaseModel):
    id: str
    batch_id: str
    namespace: str
    observed: ExtractedEntity
    status: Literal["OPEN", "RESOLVED", "SUPERSEDED"] = "OPEN"
    entity_id: str | None = None
    candidates: list[EntityResolutionCandidate] = Field(default_factory=list)
    reason: str | None = None
    confidence: float = 1.0
    method: Literal["EXACT", "AI", "NEW", "HUMAN"] = "AI"
    human_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None


class LearningBatch(BaseModel):
    id: str
    namespace: str
    source_id: str
    gap_id: str | None = None
    document_id: str | None = None
    version_id: str | None = None
    chunk_id: str | None = None
    content: str
    locator: str | None = None
    knowledge: ExtractedKnowledge
    bindings: dict[str, str] = Field(default_factory=dict)
    claim_status: Literal["PROPOSED", "CONFIRMED"] = "PROPOSED"
    revision: int = 0
    application_status: Literal["WAITING", "APPLYING", "APPLIED"] = "WAITING"


class ClarificationDetail(BaseModel):
    mention: EntityMention
    source_title: str
    document_title: str | None = None
    document_version: int | None = None
    locator: str | None = None
    excerpt: str
    deferred_claims: int
    application_pending: bool = False


class ResolveIdentityRequest(BaseModel):
    decision: Literal["MATCH", "CREATE"]
    entity_id: str | None = None
    canonical_name: NonBlankString | None = None
    reason: NonBlankString


class ResolveIdentityResponse(BaseModel):
    mention_id: str
    entity_id: str
    claims_applied: int
    pending_mentions: int
