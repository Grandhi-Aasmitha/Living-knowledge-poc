from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import EntityStatus
from app.domain.ontology import validate_entity_type


def utc_now() -> datetime:
    return datetime.now(UTC)


class Entity(BaseModel):
    id: str
    entity_type: str
    canonical_name: str
    description: str | None = None
    namespace: str
    status: EntityStatus = EntityStatus.ACTIVE
    aliases: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("entity_type")
    @classmethod
    def entity_type_must_be_allowed(cls, value: str) -> str:
        return validate_entity_type(value)
