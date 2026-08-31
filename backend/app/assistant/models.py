from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import ClaimStatus, GapPriority
from app.domain.ontology import validate_predicate


class QueryDirection(StrEnum):
    INCOMING = "INCOMING"
    OUTGOING = "OUTGOING"
    BOTH = "BOTH"


class KnowledgeStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    PROPOSED = "PROPOSED"
    INCOMPLETE = "INCOMPLETE"
    CONFLICTING = "CONFLICTING"


class KnowledgeQueryPlan(BaseModel):
    entity_names: list[str] = Field(min_length=1, max_length=3)
    predicates: list[str] = Field(default_factory=list, max_length=10)
    direction: QueryDirection = QueryDirection.BOTH

    @field_validator("entity_names")
    @classmethod
    def entity_names_must_be_meaningful(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if len(cleaned) != len(values):
            raise ValueError("entity_names must not contain blank values")
        if len(set(name.casefold() for name in cleaned)) != len(cleaned):
            raise ValueError("entity_names must be unique")
        return cleaned

    @field_validator("predicates")
    @classmethod
    def predicates_must_be_controlled(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if len(cleaned) != len(values):
            raise ValueError("predicates must not contain blank values")
        for predicate in cleaned:
            validate_predicate(predicate)
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("predicates must be unique")
        return cleaned


class MatchedEntity(BaseModel):
    id: str
    label: str
    entity_type: str
    namespace: str


class EntityResolution(BaseModel):
    requested_name: str
    matches: list[MatchedEntity]


class RetrievedEvidence(BaseModel):
    evidence_id: str
    source_id: str
    source_type: str
    source_title: str
    excerpt: str | None = None
    locator: str | None = None
    document_title: str | None = None
    document_version: int | None = None
    source_url: str | None = None


class RetrievedClaim(BaseModel):
    claim_id: str
    subject_entity_id: str
    subject_name: str
    subject_type: str
    predicate: str
    object_entity_id: str | None = None
    object_name: str | None = None
    object_value: str | None = None
    claim_status: ClaimStatus
    confidence: float
    evidence: list[RetrievedEvidence] = Field(default_factory=list)


class OpenGapContext(BaseModel):
    id: str
    entity_id: str
    gap_type: str
    description: str
    priority: GapPriority


class OpenConflictContext(BaseModel):
    id: str
    rule_id: str
    description: str
    claim_ids: list[str]


class KnowledgeContext(BaseModel):
    matched_entities: list[MatchedEntity]
    claims: list[RetrievedClaim]
    open_gaps: list[OpenGapContext] = Field(default_factory=list)
    open_conflicts: list[OpenConflictContext] = Field(default_factory=list)
    truncated: bool = False


class AnswerDraft(BaseModel):
    answer: str
    insufficient_knowledge: bool
    cited_claim_ids: list[str] = Field(default_factory=list)
    cited_evidence_ids: list[str] = Field(default_factory=list)
    uncertainty_note: str | None = None

    @field_validator("answer")
    @classmethod
    def answer_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("answer must not be blank")
        return cleaned

    @field_validator("cited_claim_ids", "cited_evidence_ids")
    @classmethod
    def citation_ids_must_not_be_blank(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if len(cleaned) != len(values):
            raise ValueError("citation IDs must not contain blanks")
        return cleaned

    @model_validator(mode="after")
    def supported_answers_require_citations(self) -> "AnswerDraft":
        if not self.insufficient_knowledge and (not self.cited_claim_ids or not self.cited_evidence_ids):
            raise ValueError("source-backed answers require cited claims and cited evidence")
        return self


class AssistantCitation(BaseModel):
    claim_id: str
    claim_status: ClaimStatus
    predicate: str
    evidence_id: str
    source_type: str
    source_title: str
    excerpt: str | None = None
    locator: str | None = None
    document_title: str | None = None
    document_version: int | None = None
    source_url: str | None = None
    subject_name: str
    object_name: str | None = None
    object_value: str | None = None


class AssistantResponse(BaseModel):
    question: str
    answer: str
    insufficient_knowledge: bool
    knowledge_status: KnowledgeStatus
    matched_entities: list[MatchedEntity]
    citations: list[AssistantCitation]
    open_gaps: list[OpenGapContext]
    open_conflicts: list[OpenConflictContext]
    context_truncated: bool


class AssistantQuestionRequest(BaseModel):
    question: str
    namespace: str = "tstvs"

    @field_validator("question")
    @classmethod
    def question_must_be_meaningful(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question is required")
        if len(cleaned) > 1000:
            raise ValueError("question must be at most 1000 characters")
        return cleaned

    @field_validator("namespace")
    @classmethod
    def namespace_must_be_meaningful(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("namespace is required")
        return cleaned


def context_for_prompt(context: KnowledgeContext) -> dict[str, Any]:
    return context.model_dump(mode="json")
