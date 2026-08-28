from datetime import UTC, datetime

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class DocumentSection(BaseModel):
    heading_path: list[str] = Field(default_factory=list)
    content: str
    locator: str | None = None


class ParsedDocument(BaseModel):
    title: str
    sections: list[DocumentSection]


class SourceDocument(BaseModel):
    id: str
    source_id: str
    external_id: str
    title: str
    filename: str
    latest_version: int
    current_content_hash: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SourceVersion(BaseModel):
    id: str
    document_id: str
    version_number: int
    content_hash: str
    storage_key: str
    created_at: datetime = Field(default_factory=utc_now)


class SourceChunk(BaseModel):
    id: str
    version_id: str
    sequence: int
    heading_path: list[str] = Field(default_factory=list)
    content: str
    locator: str | None = None
    content_hash: str
