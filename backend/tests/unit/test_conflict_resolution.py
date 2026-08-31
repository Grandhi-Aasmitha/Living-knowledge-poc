import asyncio
from datetime import UTC, datetime

import pytest

from app.conflicts.models import ConflictClaimDetail, ConflictDetail, ConflictResolutionRequest
from app.conflicts.rules import MULTIPLE_OWNERS_RULE_ID
from app.conflicts.service import ConflictResolutionService, ConflictStateError, ConflictValidationError
from app.domain.claim import Claim
from app.domain.enums import ClaimStatus, ConflictResolutionType, ConflictStatus


def run(coro):
    return asyncio.run(coro)


def claim_detail(claim_id: str, subject_id: str, subject_name: str, status: ClaimStatus = ClaimStatus.CONFIRMED) -> ConflictClaimDetail:
    return ConflictClaimDetail(
        claim_id=claim_id,
        subject_entity_id=subject_id,
        subject_name=subject_name,
        predicate="OWNS",
        object_entity_id="test:service:demo",
        object_name="Demo Service",
        status=status,
        confidence=0.8,
        created_at=datetime.now(UTC),
        evidence_count=1,
    )


def open_conflict(status: ConflictStatus = ConflictStatus.OPEN) -> ConflictDetail:
    return ConflictDetail(
        id="conflict:test",
        rule_id=MULTIPLE_OWNERS_RULE_ID,
        namespace="test",
        description="Multiple owning teams are currently recorded for Demo Service.",
        status=status,
        created_at=datetime.now(UTC),
        last_detected_at=datetime.now(UTC),
        resolved_at=None,
        resolution_type=None,
        selected_claim_id=None,
        resolution_reason=None,
        claims=[
            claim_detail("claim:a", "test:team:a", "Team A", ClaimStatus.CONFIRMED),
            claim_detail("claim:b", "test:team:b", "Team B", ClaimStatus.PROPOSED),
        ],
    )


class FakeConflictRepository:
    def __init__(self, conflict: ConflictDetail) -> None:
        self.conflict = conflict
        self.keep_calls: list[tuple[str, str]] = []
        self.both_valid_reasons: list[str] = []
        self.corrected_claims: list[Claim] = []
        self.entities = {
            "test:team:a": {"id": "test:team:a", "entity_type": "TEAM"},
            "test:team:c": {"id": "test:team:c", "entity_type": "TEAM"},
            "test:service:demo": {"id": "test:service:demo", "entity_type": "SERVICE"},
            "test:service:wrong": {"id": "test:service:wrong", "entity_type": "SERVICE"},
        }

    async def get(self, conflict_id: str) -> ConflictDetail | None:
        return self.conflict if conflict_id == self.conflict.id else None

    async def resolve_keep_claim(self, conflict_id: str, selected_claim_id: str, reason: str, resolved_at: datetime) -> str:
        self.keep_calls.append((selected_claim_id, reason))
        self.conflict = self.conflict.model_copy(update={"status": ConflictStatus.RESOLVED})
        return selected_claim_id

    async def resolve_both_valid(self, conflict_id: str, reason: str, resolved_at: datetime) -> None:
        self.both_valid_reasons.append(reason)
        self.conflict = self.conflict.model_copy(update={"status": ConflictStatus.DISMISSED})

    async def resolve_corrected(self, conflict_id: str, corrected_claim: Claim, reason: str, resolved_at: datetime) -> str:
        self.corrected_claims.append(corrected_claim)
        self.conflict = self.conflict.model_copy(update={"status": ConflictStatus.RESOLVED})
        return corrected_claim.id

    async def get_entity(self, entity_id: str):
        return self.entities.get(entity_id)


class FakeClaimRepository:
    def __init__(self) -> None:
        self.existing: Claim | None = None

    async def find_equivalent_active(self, subject_entity_id, predicate, object_entity_id, object_value, scope_entity_id):
        return self.existing


def service(conflict: ConflictDetail | None = None):
    conflict_repository = FakeConflictRepository(conflict or open_conflict())
    claim_repository = FakeClaimRepository()
    return ConflictResolutionService(conflict_repository, claim_repository), conflict_repository, claim_repository


def test_keep_claim_requires_involved_selected_claim() -> None:
    resolver, repository, _ = service()

    result = run(
        resolver.resolve(
            "conflict:test",
            ConflictResolutionRequest(decision=ConflictResolutionType.KEEP_CLAIM, selected_claim_id="claim:a", reason="Team A is current."),
        )
    )

    assert result.status == ConflictStatus.RESOLVED
    assert result.selected_claim_id == "claim:a"
    assert repository.keep_calls == [("claim:a", "Team A is current.")]


def test_keep_claim_rejects_unrelated_claim() -> None:
    resolver, _, _ = service()

    with pytest.raises(ConflictValidationError):
        run(
            resolver.resolve(
                "conflict:test",
                ConflictResolutionRequest(decision=ConflictResolutionType.KEEP_CLAIM, selected_claim_id="claim:other", reason="No."),
            )
        )


def test_both_valid_dismisses_without_corrected_claim() -> None:
    resolver, repository, _ = service()

    result = run(resolver.resolve("conflict:test", ConflictResolutionRequest(decision=ConflictResolutionType.BOTH_VALID, reason="Joint ownership.")))

    assert result.status == ConflictStatus.DISMISSED
    assert repository.both_valid_reasons == ["Joint ownership."]
    assert repository.corrected_claims == []


def test_corrected_ownership_claim_uses_existing_team_and_target() -> None:
    resolver, repository, _ = service()

    result = run(
        resolver.resolve(
            "conflict:test",
            ConflictResolutionRequest(
                decision=ConflictResolutionType.CORRECTED,
                reason="Team C owns it.",
                corrected_subject_entity_id="test:team:c",
                corrected_predicate="OWNS",
                corrected_object_entity_id="test:service:demo",
            ),
        )
    )

    corrected = repository.corrected_claims[0]
    assert result.corrected_claim_id == corrected.id
    assert corrected.status == ClaimStatus.CONFIRMED
    assert corrected.confidence == 1.0
    assert corrected.subject_entity_id == "test:team:c"
    assert corrected.predicate == "OWNS"


def test_invalid_corrected_subject_type_does_not_mutate() -> None:
    resolver, repository, _ = service()

    with pytest.raises(ConflictValidationError):
        run(
            resolver.resolve(
                "conflict:test",
                ConflictResolutionRequest(
                    decision=ConflictResolutionType.CORRECTED,
                    reason="Wrong type.",
                    corrected_subject_entity_id="test:service:wrong",
                    corrected_predicate="OWNS",
                    corrected_object_entity_id="test:service:demo",
                ),
            )
        )

    assert repository.corrected_claims == []


def test_repeat_resolution_is_rejected() -> None:
    resolver, _, _ = service(open_conflict(status=ConflictStatus.RESOLVED))

    with pytest.raises(ConflictStateError):
        run(resolver.resolve("conflict:test", ConflictResolutionRequest(decision=ConflictResolutionType.BOTH_VALID, reason="Done.")))
