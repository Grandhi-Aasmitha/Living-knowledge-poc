from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    id: str
    label: str
    entity_type: str
    namespace: str
    status: str
    aliases: list[str] = Field(default_factory=list)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    predicate: str
    claim_status: str
    confidence: float
    evidence_count: int


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool


class EvidenceSummary(BaseModel):
    id: str
    excerpt: str | None
    locator: str | None
    source_id: str
    source_type: str
    source_title: str
    document_title: str | None
    document_version: int | None
    chunk_locator: str | None
    is_current: bool = True


class ClaimProvenanceResponse(BaseModel):
    claim_id: str
    subject_entity_id: str
    subject_name: str
    predicate: str
    object_entity_id: str | None
    object_name: str | None
    object_value: str | None
    status: str
    confidence: float
    evidence: list[EvidenceSummary]
