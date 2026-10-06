from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.domain.enums import GapPriority, GapStatus
from app.domain.validation import NonBlankString


def utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeGap(BaseModel):
    id: NonBlankString = Field(default_factory=lambda: str(uuid4()))
    entity_id: NonBlankString
    gap_type: NonBlankString
    description: NonBlankString
    priority: GapPriority
    status: GapStatus = GapStatus.OPEN
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None
    detection_rule_id: NonBlankString | None = None
    last_detected_at: datetime | None = None
