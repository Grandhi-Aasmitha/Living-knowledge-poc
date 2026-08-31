from pydantic import BaseModel, Field

from app.assistant.models import KnowledgeStatus


class GoldenCase(BaseModel):
    id: str
    question: str
    namespace: str
    expected_entity_ids: list[str] = Field(default_factory=list)
    required_claim_ids: list[str] = Field(default_factory=list)
    forbidden_claim_ids: list[str] = Field(default_factory=list)
    expect_insufficient_knowledge: bool
    expected_knowledge_status: KnowledgeStatus


class EvaluationMetrics(BaseModel):
    total_cases: int
    passed_cases: int
    failed_cases: int
    required_claim_recall: float
    citation_validity_rate: float
    unsupported_refusal_rate: float
