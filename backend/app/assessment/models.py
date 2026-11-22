from typing import Literal

from pydantic import BaseModel, Field


AssessmentStage = Literal[
    "SOURCE_AND_DEPENDENCIES",
    "TARGET_DISCOVERY",
    "CAPABILITY_PARITY",
    "OPTIONS_EVALUATION",
    "SECURITY_AND_NFR",
    "RECOMMENDATION",
]

STAGES: tuple[AssessmentStage, ...] = (
    "SOURCE_AND_DEPENDENCIES",
    "TARGET_DISCOVERY",
    "CAPABILITY_PARITY",
    "OPTIONS_EVALUATION",
    "SECURITY_AND_NFR",
    "RECOMMENDATION",
)


class StepFinding(BaseModel):
    summary: str = Field(min_length=1)
    completeness: Literal["FULL", "PARTIAL", "IN_PROGRESS"]
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    missing_question: str | None = None
    outcome: Literal["MIGRATE", "MODERNIZE", "RETIRE", "RETAIN", "NEEDS_REVIEW"] | None = None
    risks: list[str] = Field(default_factory=list, max_length=8)
    prerequisites: list[str] = Field(default_factory=list, max_length=8)


class Finding(BaseModel):
    stage: AssessmentStage
    summary: str
    completeness: Literal["FULL", "PARTIAL", "IN_PROGRESS"]
    claim_ids: list[str]
    evidence_ids: list[str]
    outcome: Literal["MIGRATE", "MODERNIZE", "RETIRE", "RETAIN", "NEEDS_REVIEW"] | None = None
    risks: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)


class AssessmentView(BaseModel):
    assessment_id: str
    namespace: str
    source_application: str
    target_application: str | None = None
    status: Literal["RUNNING", "WAITING_FOR_INPUT", "WAITING_FOR_REVIEW", "APPROVED"]
    current_stage: AssessmentStage | None = None
    question: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    clarifications: list[dict[str, str]] = Field(default_factory=list)
    review_history: list[dict[str, str]] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    context_limited: bool = False


class StartAssessmentRequest(BaseModel):
    namespace: str = Field(min_length=1, max_length=120)
    source_application: str = Field(min_length=1, max_length=200)
    target_application: str | None = Field(default=None, max_length=200)


class AnswerAssessmentRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


class ReviewAssessmentRequest(BaseModel):
    decision: Literal["APPROVE", "REVISE"]
    reviewer: str = Field(min_length=1, max_length=120)
    comment: str = Field(default="", max_length=2000)
