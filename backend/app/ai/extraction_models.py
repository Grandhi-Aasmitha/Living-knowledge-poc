from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.ontology import validate_entity_type, validate_predicate


class ExtractedEntity(BaseModel):
    temporary_id: str
    entity_type: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None

    @field_validator("temporary_id", "name")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        stripped = value.strip()
        if stripped == "":
            raise ValueError("value must not be empty")
        return stripped

    @field_validator("entity_type")
    @classmethod
    def entity_type_must_be_allowed(cls, value: str) -> str:
        return validate_entity_type(value)


class ExtractedClaim(BaseModel):
    subject: str
    predicate: str
    object_entity: str | None = None
    object_value: str | None = None
    scope_entity: str | None = None
    confidence: float
    evidence_text: str

    @field_validator("subject", "evidence_text")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        stripped = value.strip()
        if stripped == "":
            raise ValueError("value must not be empty")
        return stripped

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
    def object_must_be_exactly_one_kind(self) -> "ExtractedClaim":
        has_entity = self.object_entity is not None and self.object_entity.strip() != ""
        has_value = self.object_value is not None and self.object_value.strip() != ""
        if has_entity == has_value:
            raise ValueError("exactly one of object_entity or object_value must be populated")
        return self


class ExtractedKnowledge(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)
    unresolved_terms: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def claim_references_must_exist(self) -> "ExtractedKnowledge":
        entity_ids = {entity.temporary_id for entity in self.entities}
        for claim in self.claims:
            refs = [claim.subject, claim.object_entity, claim.scope_entity]
            for ref in refs:
                if ref is not None and ref.strip() != "" and ref not in entity_ids:
                    raise ValueError(f"claim reference does not exist: {ref}")
        return self
