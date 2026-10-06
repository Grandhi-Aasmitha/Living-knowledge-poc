from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import ClaimStatus
from app.domain.ontology import validate_predicate
from app.domain.validation import NonBlankString


def utc_now() -> datetime:
    return datetime.now(UTC)


class Claim(BaseModel):
    id: NonBlankString = Field(default_factory=lambda: str(uuid4()))
    subject_entity_id: NonBlankString
    predicate: NonBlankString
    object_entity_id: NonBlankString | None = None
    object_value: NonBlankString | None = None
    scope_entity_id: NonBlankString | None = None
    confidence: float = 1.0
    status: ClaimStatus
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("predicate")
    @classmethod
    def predicate_must_be_allowed(cls, value: str) -> str:
        return validate_predicate(value)

    @field_validator("confidence")
    @classmethod
    def confidence_must_be_between_zero_and_one(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return value

    @model_validator(mode="after")
    def object_and_temporal_values_must_be_valid(self) -> "Claim":
        has_entity_object = self.object_entity_id is not None
        has_literal_object = self.object_value is not None

        if has_entity_object == has_literal_object:
            raise ValueError("exactly one of object_entity_id or object_value must be populated")

        if self.valid_from is not None and self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must be greater than or equal to valid_from")

        return self
