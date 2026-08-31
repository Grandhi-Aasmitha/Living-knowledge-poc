from datetime import UTC, datetime

from app.conflicts.models import ConflictDetectionResult, ConflictFinding, ConflictResolutionRequest, ConflictResolutionResult, KnowledgeConflict
from app.conflicts.rules import MULTIPLE_OWNERS_RULE_ID, MULTIPLE_PART_OF_RULE_ID
from app.domain.claim import Claim
from app.domain.enums import ClaimStatus, ConflictResolutionType, ConflictStatus
from app.domain.identifiers import build_conflict_id, stable_claim_id
from app.repositories.claim_repository import ClaimRepository
from app.repositories.conflict_repository import ConflictRepository


class ConflictStateError(RuntimeError):
    pass


class ConflictValidationError(ValueError):
    pass


class ConflictDetectionService:
    def __init__(self, conflict_repository: ConflictRepository) -> None:
        self._conflict_repository = conflict_repository

    async def detect(self, namespace: str) -> ConflictDetectionResult:
        detected_at = datetime.now(UTC)
        findings = await self._conflict_repository.detect_all(namespace)
        current_ids = {self._conflict_id(finding) for finding in findings}
        created = 0
        existing = 0

        for finding in findings:
            conflict_id = self._conflict_id(finding)
            existing_conflict = await self._conflict_repository.get_conflict(conflict_id)
            if existing_conflict is None:
                await self._conflict_repository.create(
                    KnowledgeConflict(
                        id=conflict_id,
                        rule_id=finding.rule_id,
                        namespace=finding.namespace,
                        description=finding.description,
                        status=ConflictStatus.OPEN,
                        created_at=detected_at,
                        last_detected_at=detected_at,
                    ),
                    finding.claim_ids,
                )
                created += 1
            elif existing_conflict.status == ConflictStatus.OPEN:
                await self._conflict_repository.touch(conflict_id, detected_at)
                existing += 1
            elif existing_conflict.status == ConflictStatus.DISMISSED:
                existing += 1

        auto_cleared = 0
        for open_conflict in await self._conflict_repository.list_open(namespace):
            if open_conflict.id not in current_ids:
                await self._conflict_repository.auto_clear(open_conflict.id, detected_at)
                auto_cleared += 1

        return ConflictDetectionResult(
            namespace=namespace,
            findings_detected=len(findings),
            conflicts_created=created,
            conflicts_existing=existing,
            conflicts_auto_cleared=auto_cleared,
            open_conflicts=await self._conflict_repository.count_open(namespace),
        )

    def _conflict_id(self, finding: ConflictFinding) -> str:
        return build_conflict_id(finding.rule_id, finding.claim_ids)


class ConflictResolutionService:
    def __init__(self, conflict_repository: ConflictRepository, claim_repository: ClaimRepository) -> None:
        self._conflict_repository = conflict_repository
        self._claim_repository = claim_repository

    async def resolve(self, conflict_id: str, request: ConflictResolutionRequest) -> ConflictResolutionResult:
        conflict = await self._conflict_repository.get(conflict_id)
        if conflict is None:
            raise ConflictValidationError("Conflict does not exist")
        if conflict.status != ConflictStatus.OPEN:
            raise ConflictStateError("Conflict is already resolved")

        resolved_at = datetime.now(UTC)
        if request.decision == ConflictResolutionType.KEEP_CLAIM:
            selected_claim_id = request.selected_claim_id or ""
            if selected_claim_id not in {claim.claim_id for claim in conflict.claims}:
                raise ConflictValidationError("Selected claim is not involved in this conflict")
            await self._conflict_repository.resolve_keep_claim(conflict_id, selected_claim_id, request.reason, resolved_at)
            return ConflictResolutionResult(
                conflict_id=conflict_id,
                status=ConflictStatus.RESOLVED,
                resolution_type=ConflictResolutionType.KEEP_CLAIM,
                selected_claim_id=selected_claim_id,
            )

        if request.decision == ConflictResolutionType.BOTH_VALID:
            await self._conflict_repository.resolve_both_valid(conflict_id, request.reason, resolved_at)
            return ConflictResolutionResult(
                conflict_id=conflict_id,
                status=ConflictStatus.DISMISSED,
                resolution_type=ConflictResolutionType.BOTH_VALID,
            )

        if request.decision == ConflictResolutionType.CORRECTED:
            corrected_claim = await self._build_corrected_claim(conflict, request, resolved_at)
            corrected_claim_id = await self._conflict_repository.resolve_corrected(conflict_id, corrected_claim, request.reason, resolved_at)
            return ConflictResolutionResult(
                conflict_id=conflict_id,
                status=ConflictStatus.RESOLVED,
                resolution_type=ConflictResolutionType.CORRECTED,
                corrected_claim_id=corrected_claim_id,
            )

        raise ConflictValidationError("Unsupported resolution decision")

    async def _build_corrected_claim(self, conflict, request: ConflictResolutionRequest, resolved_at: datetime) -> Claim:
        subject_id = request.corrected_subject_entity_id or ""
        predicate = request.corrected_predicate or ""
        object_id = request.corrected_object_entity_id or ""
        scope_id = request.corrected_scope_entity_id
        subject = await self._conflict_repository.get_entity(subject_id)
        object_entity = await self._conflict_repository.get_entity(object_id)
        scope_entity = await self._conflict_repository.get_entity(scope_id) if scope_id is not None else None
        if subject is None or object_entity is None or (scope_id is not None and scope_entity is None):
            raise ConflictValidationError("Corrected claim entities must already exist")

        if conflict.rule_id == MULTIPLE_OWNERS_RULE_ID:
            involved_objects = {claim.object_entity_id for claim in conflict.claims}
            if subject.get("entity_type") != "TEAM" or predicate != "OWNS" or object_id not in involved_objects:
                raise ConflictValidationError("Corrected ownership claim must be TEAM OWNS the conflicted target")
        elif conflict.rule_id == MULTIPLE_PART_OF_RULE_ID:
            involved_subjects = {claim.subject_entity_id for claim in conflict.claims}
            if subject_id not in involved_subjects or predicate != "PART_OF":
                raise ConflictValidationError("Corrected PART_OF claim must use the conflicted subject and PART_OF predicate")
        else:
            raise ConflictValidationError("Unsupported conflict rule")

        existing = await self._claim_repository.find_equivalent_active(
            subject_entity_id=subject_id,
            predicate=predicate,
            object_entity_id=object_id,
            object_value=None,
            scope_entity_id=scope_id,
        )
        if existing is not None:
            return existing.model_copy(update={"status": ClaimStatus.CONFIRMED, "confidence": 1.0, "updated_at": resolved_at})

        return Claim(
            id=stable_claim_id(subject_id, predicate, object_id, None, scope_id),
            subject_entity_id=subject_id,
            predicate=predicate,
            object_entity_id=object_id,
            scope_entity_id=scope_id,
            confidence=1.0,
            status=ClaimStatus.CONFIRMED,
            created_at=resolved_at,
            updated_at=resolved_at,
        )
