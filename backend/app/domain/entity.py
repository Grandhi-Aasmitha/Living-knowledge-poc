from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import EntityStatus
from app.domain.ontology import validate_entity_type
from app.domain.validation import NonBlankString


def utc_now() -> datetime:
    return datetime.now(UTC)


class Entity(BaseModel):
    id: NonBlankString
    entity_type: NonBlankString
    canonical_name: NonBlankString
    description: NonBlankString | None = None
    namespace: NonBlankString
    status: EntityStatus = EntityStatus.ACTIVE
    aliases: list[NonBlankString] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("entity_type")
    @classmethod
    def entity_type_must_be_allowed(cls, value: str) -> str:
        return validate_entity_type(value)
