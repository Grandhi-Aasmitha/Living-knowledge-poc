from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.domain.enums import GapPriority, GapStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeGap(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    entity_id: str
    gap_type: str
    description: str
    priority: GapPriority
    status: GapStatus = GapStatus.OPEN
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None
    detection_rule_id: str | None = None
    last_detected_at: datetime | None = None
