import asyncio
from datetime import UTC, datetime

from app.completeness.models import GapFinding
from app.completeness.rules import MISSING_CONSUMER_RULE_ID
from app.completeness.service import GapDetectionService
from app.domain.enums import GapPriority, GapStatus
from app.domain.gap import KnowledgeGap
from app.domain.identifiers import build_automatic_gap_id


def run(coro):
    return asyncio.run(coro)


def finding(entity_id: str = "test:topic:dispatch") -> GapFinding:
    return GapFinding(
        rule_id=MISSING_CONSUMER_RULE_ID,
        gap_type="MISSING_CONSUMER",
        entity_id=entity_id,
        entity_name="Dispatch Event",
        description="No consumer is currently known for Dispatch Event.",
        priority=GapPriority.HIGH,
    )


class FakeCompletenessRepository:
    def __init__(self, findings: list[GapFinding]) -> None:
        self.findings = findings

    async def detect_all(self, namespace: str) -> list[GapFinding]:
        return self.findings


class FakeGapRepository:
    def __init__(self) -> None:
        self.gaps: dict[str, KnowledgeGap] = {}

    async def create(self, gap: KnowledgeGap) -> KnowledgeGap:
        self.gaps[gap.id] = gap
        return gap

    async def get(self, gap_id: str) -> KnowledgeGap | None:
        return self.gaps.get(gap_id)

    async def find_open_for_entity_and_type(self, entity_id: str, gap_type: str) -> KnowledgeGap | None:
        for gap in self.gaps.values():
            if gap.entity_id == entity_id and gap.gap_type == gap_type and gap.status == GapStatus.OPEN:
                return gap
        return None

    async def list_automatic_for_namespace(self, namespace: str) -> list[KnowledgeGap]:
        return [gap for gap in self.gaps.values() if gap.detection_rule_id is not None]

    async def resolve(self, gap_id: str) -> KnowledgeGap | None:
        gap = self.gaps.get(gap_id)
        if gap is None:
            return None
        resolved = gap.model_copy(update={"status": GapStatus.RESOLVED, "resolved_at": datetime.now(UTC)})
        self.gaps[gap_id] = resolved
        return resolved

    async def reopen(self, gap_id: str, detected_at: datetime) -> KnowledgeGap | None:
        gap = self.gaps.get(gap_id)
        if gap is None:
            return None
        reopened = gap.model_copy(update={"status": GapStatus.OPEN, "resolved_at": None, "last_detected_at": detected_at})
        self.gaps[gap_id] = reopened
        return reopened

    async def touch_detection(self, gap_id: str, detected_at: datetime) -> KnowledgeGap | None:
        gap = self.gaps.get(gap_id)
        if gap is None:
            return None
        touched = gap.model_copy(update={"last_detected_at": detected_at})
        self.gaps[gap_id] = touched
        return touched


def build_service(findings: list[GapFinding], gaps: FakeGapRepository | None = None) -> tuple[GapDetectionService, FakeGapRepository]:
    gap_repository = gaps or FakeGapRepository()
    return GapDetectionService(FakeCompletenessRepository(findings), gap_repository), gap_repository


def automatic_gap_id(item: GapFinding) -> str:
    return build_automatic_gap_id(item.rule_id, item.entity_id)


def test_new_finding_creates_automatic_gap() -> None:
    item = finding()
    service, gaps = build_service([item])

    result = run(service.detect("test"))

    assert result.findings_detected == 1
    assert result.gaps_created == 1
    assert result.gaps_existing == 0
    assert result.gaps_reopened == 0
    assert result.gaps_resolved == 0
    assert result.open_automatic_gaps == 1
    created = gaps.gaps[automatic_gap_id(item)]
    assert created.detection_rule_id == item.rule_id
    assert created.last_detected_at is not None


def test_second_identical_detection_does_not_duplicate() -> None:
    item = finding()
    service, gaps = build_service([item])

    first = run(service.detect("test"))
    second = run(service.detect("test"))

    assert first.gaps_created == 1
    assert second.gaps_created == 0
    assert second.gaps_existing == 1
    assert len(gaps.gaps) == 1


def test_manual_open_gap_prevents_automatic_duplicate() -> None:
    item = finding()
    service, gaps = build_service([item])
    gaps.gaps["manual:gap"] = KnowledgeGap(
        id="manual:gap",
        entity_id=item.entity_id,
        gap_type=item.gap_type,
        description="Manual gap",
        priority=GapPriority.HIGH,
    )

    result = run(service.detect("test"))

    assert result.gaps_created == 0
    assert result.gaps_existing == 1
    assert automatic_gap_id(item) not in gaps.gaps


def test_automatic_resolved_gap_reopens() -> None:
    item = finding()
    gap_id = automatic_gap_id(item)
    service, gaps = build_service([item])
    gaps.gaps[gap_id] = KnowledgeGap(
        id=gap_id,
        entity_id=item.entity_id,
        gap_type=item.gap_type,
        description=item.description,
        priority=item.priority,
        status=GapStatus.RESOLVED,
        detection_rule_id=item.rule_id,
        resolved_at=datetime.now(UTC),
    )

    result = run(service.detect("test"))

    assert result.gaps_reopened == 1
    assert gaps.gaps[gap_id].status == GapStatus.OPEN
    assert gaps.gaps[gap_id].resolved_at is None


def test_automatic_open_gap_resolves_when_finding_disappears() -> None:
    item = finding()
    gap_id = automatic_gap_id(item)
    service, gaps = build_service([])
    gaps.gaps[gap_id] = KnowledgeGap(
        id=gap_id,
        entity_id=item.entity_id,
        gap_type=item.gap_type,
        description=item.description,
        priority=item.priority,
        detection_rule_id=item.rule_id,
    )

    result = run(service.detect("test"))

    assert result.gaps_resolved == 1
    assert result.open_automatic_gaps == 0
    assert gaps.gaps[gap_id].status == GapStatus.RESOLVED


def test_manual_gap_is_not_auto_resolved() -> None:
    service, gaps = build_service([])
    gaps.gaps["manual:gap"] = KnowledgeGap(
        id="manual:gap",
        entity_id="test:topic:dispatch",
        gap_type="MISSING_CONSUMER",
        description="Manual gap",
        priority=GapPriority.HIGH,
    )

    result = run(service.detect("test"))

    assert result.gaps_resolved == 0
    assert gaps.gaps["manual:gap"].status == GapStatus.OPEN
