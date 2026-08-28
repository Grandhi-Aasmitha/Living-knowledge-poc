from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.ontology import validate_entity_type, validate_predicate


class QuestionDraft(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def question_must_not_be_empty(cls, value: str) -> str:
        question = value.strip()
        if question == "":
            raise ValueError("question must not be empty")
        return question


class AnswerInterpretation(BaseModel):
    can_resolve: bool
    entity_name: str | None = None
    entity_type: str | None = None
    reason: str | None = None

    @field_validator("entity_name")
    @classmethod
    def entity_name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if stripped == "":
            raise ValueError("entity_name must not be blank")
        return stripped

    @field_validator("entity_type")
    @classmethod
    def entity_type_must_be_allowed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_entity_type(value.strip())

    @model_validator(mode="after")
    def resolvable_answer_requires_entity(self) -> "AnswerInterpretation":
        if self.can_resolve and (self.entity_name is None or self.entity_type is None):
            raise ValueError("entity_name and entity_type are required when can_resolve is true")
        if not self.can_resolve and (self.entity_name is not None or self.entity_type is not None):
            raise ValueError("entity_name and entity_type must be empty when can_resolve is false")
        return self


class ClaimCandidate(BaseModel):
    subject_entity_id: str
    predicate: str
    object_entity_id: str
    confidence: float = 1.0

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
