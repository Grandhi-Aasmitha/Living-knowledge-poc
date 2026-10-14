from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.domain.validation import NonBlankString


def utc_now() -> datetime:
    return datetime.now(UTC)


class Evidence(BaseModel):
    id: NonBlankString = Field(default_factory=lambda: str(uuid4()))
    claim_id: NonBlankString
    source_id: NonBlankString
    source_chunk_id: NonBlankString | None = None
    excerpt: NonBlankString | None = None
    locator: NonBlankString | None = None
    is_current: bool = True
    created_at: datetime = Field(default_factory=utc_now)
