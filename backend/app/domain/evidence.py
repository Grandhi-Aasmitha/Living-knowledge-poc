from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    claim_id: str
    source_id: str
    source_chunk_id: str | None = None
    excerpt: str | None = None
    locator: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
