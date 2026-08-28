from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.domain.enums import SourceType


def utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeSource(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_type: SourceType
    title: str
    external_id: str | None = None
    version: str | None = None
    source_url: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
