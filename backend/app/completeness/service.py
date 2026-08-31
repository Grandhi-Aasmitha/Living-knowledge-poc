from datetime import UTC, datetime

from app.completeness.models import GapDetectionResult, GapFinding
from app.domain.enums import GapStatus
from app.domain.gap import KnowledgeGap
from app.domain.identifiers import build_automatic_gap_id
from app.repositories.completeness_repository import CompletenessRepository
from app.repositories.gap_repository import GapRepository


class GapDetectionService:
    def __init__(
        self,
        completeness_repository: CompletenessRepository,
        gap_repository: GapRepository,
    ) -> None:
        self._completeness_repository = completeness_repository
        self._gap_repository = gap_repository

    async def detect(self, namespace: str) -> GapDetectionResult:
        detected_at = datetime.now(UTC)
        findings = await self._completeness_repository.detect_all(namespace)
        current_automatic_gap_ids = {
            build_automatic_gap_id(finding.rule_id, finding.entity_id) for finding in findings
        }

        gaps_created = 0
        gaps_existing = 0
        gaps_reopened = 0

        for finding in findings:
            automatic_gap_id = build_automatic_gap_id(finding.rule_id, finding.entity_id)
            automatic_gap = await self._gap_repository.get(automatic_gap_id)
            if automatic_gap is None:
                open_gap = await self._gap_repository.find_open_for_entity_and_type(
                    entity_id=finding.entity_id,
                    gap_type=finding.gap_type,
                )
                if open_gap is not None:
                    gaps_existing += 1
                    continue
                await self._gap_repository.create(self._gap_from_finding(finding, automatic_gap_id, detected_at))
                gaps_created += 1
                continue

            if automatic_gap.status == GapStatus.RESOLVED:
                await self._gap_repository.reopen(automatic_gap.id, detected_at)
                gaps_reopened += 1
            elif automatic_gap.status == GapStatus.OPEN:
                await self._gap_repository.touch_detection(automatic_gap.id, detected_at)
                gaps_existing += 1
            else:
                gaps_existing += 1

        gaps_resolved = 0
        automatic_gaps = await self._gap_repository.list_automatic_for_namespace(namespace)
        for gap in automatic_gaps:
            if gap.status == GapStatus.OPEN and gap.id not in current_automatic_gap_ids:
                await self._gap_repository.resolve(gap.id)
                gaps_resolved += 1

        refreshed_automatic_gaps = await self._gap_repository.list_automatic_for_namespace(namespace)
        open_automatic_gaps = sum(1 for gap in refreshed_automatic_gaps if gap.status == GapStatus.OPEN)

        return GapDetectionResult(
            namespace=namespace,
            findings_detected=len(findings),
            gaps_created=gaps_created,
            gaps_existing=gaps_existing,
            gaps_reopened=gaps_reopened,
            gaps_resolved=gaps_resolved,
            open_automatic_gaps=open_automatic_gaps,
        )

    def _gap_from_finding(self, finding: GapFinding, gap_id: str, detected_at: datetime) -> KnowledgeGap:
        return KnowledgeGap(
            id=gap_id,
            entity_id=finding.entity_id,
            gap_type=finding.gap_type,
            description=finding.description,
            priority=finding.priority,
            status=GapStatus.OPEN,
            created_at=detected_at,
            detection_rule_id=finding.rule_id,
            last_detected_at=detected_at,
        )
