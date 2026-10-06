from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.domain.enums import SourceType
from app.domain.validation import NonBlankString


def utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeSource(BaseModel):
    id: NonBlankString = Field(default_factory=lambda: str(uuid4()))
    source_type: SourceType
    title: NonBlankString
    external_id: NonBlankString | None = None
    version: NonBlankString | None = None
    source_url: NonBlankString | None = None
    created_at: datetime = Field(default_factory=utc_now)
