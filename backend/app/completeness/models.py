from pydantic import BaseModel

from app.domain.enums import GapPriority


class GapFinding(BaseModel):
    rule_id: str
    gap_type: str
    entity_id: str
    entity_name: str
    description: str
    priority: GapPriority


class GapDetectionResult(BaseModel):
    namespace: str
    findings_detected: int
    gaps_created: int
    gaps_existing: int
    gaps_reopened: int
    gaps_resolved: int
    open_automatic_gaps: int
