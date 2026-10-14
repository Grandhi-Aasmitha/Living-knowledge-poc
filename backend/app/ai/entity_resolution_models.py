from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class EntityResolutionAction(StrEnum):
    MATCH = "MATCH"
    CREATE = "CREATE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class EntityResolutionCandidate(BaseModel):
    entity_id: str
    canonical_name: str
    entity_type: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    lexical_score: float = Field(ge=0.0, le=1.0)


class EntityResolutionDecision(BaseModel):
    action: EntityResolutionAction
    matched_entity_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str

    @model_validator(mode="after")
    def matched_entity_is_only_used_for_match(self) -> "EntityResolutionDecision":
        if self.action == EntityResolutionAction.MATCH and self.matched_entity_id is None:
            raise ValueError("matched_entity_id is required for MATCH")
        if self.action != EntityResolutionAction.MATCH and self.matched_entity_id is not None:
            raise ValueError("matched_entity_id is only allowed for MATCH")
        return self
