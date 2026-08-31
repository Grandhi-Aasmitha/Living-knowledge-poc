import asyncio
from datetime import UTC, datetime

from app.conflicts.models import ConflictFinding, KnowledgeConflict
from app.conflicts.rules import MULTIPLE_OWNERS_RULE_ID
from app.conflicts.service import ConflictDetectionService
from app.domain.enums import ConflictResolutionType, ConflictStatus
from app.domain.identifiers import build_conflict_id


def run(coro):
    return asyncio.run(coro)


def finding(claim_ids: list[str] | None = None) -> ConflictFinding:
    return ConflictFinding(
        rule_id=MULTIPLE_OWNERS_RULE_ID,
        namespace="test-conflict",
        description="Multiple owning teams are currently recorded for Demo Service.",
        claim_ids=claim_ids or ["claim:b", "claim:a"],
    )


class FakeConflictRepository:
    def __init__(self, findings: list[ConflictFinding]) -> None:
        self.findings = findings
        self.conflicts: dict[str, KnowledgeConflict] = {}
        self.created_claim_ids: dict[str, list[str]] = {}

    async def detect_all(self, namespace: str) -> list[ConflictFinding]:
        return self.findings

    async def get_conflict(self, conflict_id: str) -> KnowledgeConflict | None:
        return self.conflicts.get(conflict_id)

    async def create(self, conflict: KnowledgeConflict, claim_ids: list[str]) -> KnowledgeConflict:
        self.conflicts[conflict.id] = conflict
        self.created_claim_ids[conflict.id] = claim_ids
        return conflict

    async def touch(self, conflict_id: str, detected_at: datetime) -> None:
        self.conflicts[conflict_id] = self.conflicts[conflict_id].model_copy(update={"last_detected_at": detected_at})

    async def list_open(self, namespace: str) -> list[KnowledgeConflict]:
        return [conflict for conflict in self.conflicts.values() if conflict.namespace == namespace and conflict.status == ConflictStatus.OPEN]

    async def auto_clear(self, conflict_id: str, resolved_at: datetime) -> None:
        self.conflicts[conflict_id] = self.conflicts[conflict_id].model_copy(
            update={"status": ConflictStatus.RESOLVED, "resolution_type": ConflictResolutionType.AUTO_CLEARED, "resolved_at": resolved_at}
        )

    async def count_open(self, namespace: str) -> int:
        return len(await self.list_open(namespace))


def conflict_id(item: ConflictFinding) -> str:
    return build_conflict_id(item.rule_id, item.claim_ids)


def test_new_conflict_is_created_with_sorted_claim_signature() -> None:
    item = finding()
    repository = FakeConflictRepository([item])

    result = run(ConflictDetectionService(repository).detect("test-conflict"))

    assert result.findings_detected == 1
    assert result.conflicts_created == 1
    assert result.open_conflicts == 1
    created_id = conflict_id(item)
    assert repository.created_claim_ids[created_id] == ["claim:a", "claim:b"]


def test_repeated_detection_is_idempotent() -> None:
    item = finding()
    repository = FakeConflictRepository([item])
    service = ConflictDetectionService(repository)

    first = run(service.detect("test-conflict"))
    second = run(service.detect("test-conflict"))

    assert first.conflicts_created == 1
    assert second.conflicts_created == 0
    assert second.conflicts_existing == 1
    assert len(repository.conflicts) == 1


def test_open_conflict_auto_clears_when_finding_disappears() -> None:
    item = finding()
    repository = FakeConflictRepository([])
    repository.conflicts[conflict_id(item)] = KnowledgeConflict(
        id=conflict_id(item),
        rule_id=item.rule_id,
        namespace=item.namespace,
        description=item.description,
    )

    result = run(ConflictDetectionService(repository).detect("test-conflict"))

    assert result.conflicts_auto_cleared == 1
    assert repository.conflicts[conflict_id(item)].status == ConflictStatus.RESOLVED
    assert repository.conflicts[conflict_id(item)].resolution_type == ConflictResolutionType.AUTO_CLEARED


def test_dismissed_identical_conflict_does_not_reopen() -> None:
    item = finding()
    repository = FakeConflictRepository([item])
    repository.conflicts[conflict_id(item)] = KnowledgeConflict(
        id=conflict_id(item),
        rule_id=item.rule_id,
        namespace=item.namespace,
        description=item.description,
        status=ConflictStatus.DISMISSED,
        resolution_type=ConflictResolutionType.BOTH_VALID,
    )

    result = run(ConflictDetectionService(repository).detect("test-conflict"))

    assert result.conflicts_created == 0
    assert result.conflicts_existing == 1
    assert repository.conflicts[conflict_id(item)].status == ConflictStatus.DISMISSED
