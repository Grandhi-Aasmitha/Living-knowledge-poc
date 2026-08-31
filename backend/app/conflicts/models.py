from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import ClaimStatus, ConflictResolutionType, ConflictStatus


class KnowledgeConflict(BaseModel):
    id: str
    rule_id: str
    namespace: str
    description: str
    status: ConflictStatus = ConflictStatus.OPEN
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    resolution_type: ConflictResolutionType | None = None
    selected_claim_id: str | None = None
    resolution_reason: str | None = None


class ConflictFinding(BaseModel):
    rule_id: str
    namespace: str
    description: str
    claim_ids: list[str]

    @field_validator("claim_ids")
    @classmethod
    def claim_ids_must_be_distinct(cls, claim_ids: list[str]) -> list[str]:
        unique_claim_ids = sorted(set(claim_ids))
        if len(unique_claim_ids) < 2:
            raise ValueError("ConflictFinding requires at least two distinct claim IDs")
        return unique_claim_ids


class ConflictDetectionResult(BaseModel):
    namespace: str
    findings_detected: int
    conflicts_created: int
    conflicts_existing: int
    conflicts_auto_cleared: int
    open_conflicts: int


class ConflictEvidenceSummary(BaseModel):
    id: str
    excerpt: str | None
    locator: str | None
    source_id: str
    source_type: str
    source_title: str
    document_title: str | None = None
    document_version: int | None = None
    chunk_locator: str | None = None


class ConflictClaimDetail(BaseModel):
    claim_id: str
    subject_entity_id: str
    subject_name: str
    predicate: str
    object_entity_id: str | None
    object_name: str | None
    status: ClaimStatus
    confidence: float
    created_at: datetime
    evidence_count: int
    evidence: list[ConflictEvidenceSummary] = Field(default_factory=list)


class ConflictDetail(BaseModel):
    id: str
    rule_id: str
    namespace: str
    description: str
    status: ConflictStatus
    created_at: datetime
    last_detected_at: datetime
    resolved_at: datetime | None
    resolution_type: ConflictResolutionType | None
    selected_claim_id: str | None
    resolution_reason: str | None
    claims: list[ConflictClaimDetail] = Field(default_factory=list)


class ConflictSummary(BaseModel):
    id: str
    rule_id: str
    namespace: str
    description: str
    status: ConflictStatus
    created_at: datetime
    last_detected_at: datetime
    resolved_at: datetime | None
    resolution_type: ConflictResolutionType | None
    selected_claim_id: str | None
    claim_count: int


class ConflictResolutionRequest(BaseModel):
    decision: ConflictResolutionType
    selected_claim_id: str | None = None
    reason: str
    corrected_subject_entity_id: str | None = None
    corrected_predicate: str | None = None
    corrected_object_entity_id: str | None = None
    corrected_scope_entity_id: str | None = None

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, reason: str) -> str:
        if not reason.strip():
            raise ValueError("resolution reason is required")
        return reason.strip()

    @model_validator(mode="after")
    def required_fields_must_match_decision(self) -> "ConflictResolutionRequest":
        if self.decision == ConflictResolutionType.KEEP_CLAIM and self.selected_claim_id is None:
            raise ValueError("selected_claim_id is required for KEEP_CLAIM")
        if self.decision == ConflictResolutionType.CORRECTED:
            missing = [
                field_name
                for field_name in ("corrected_subject_entity_id", "corrected_predicate", "corrected_object_entity_id")
                if getattr(self, field_name) is None
            ]
            if missing:
                raise ValueError("corrected subject, predicate, and object entity are required for CORRECTED")
        if self.decision == ConflictResolutionType.AUTO_CLEARED:
            raise ValueError("AUTO_CLEARED is reserved for automatic conflict lifecycle management")
        return self


class ConflictResolutionResult(BaseModel):
    conflict_id: str
    status: ConflictStatus
    resolution_type: ConflictResolutionType
    selected_claim_id: str | None = None
    corrected_claim_id: str | None = None
