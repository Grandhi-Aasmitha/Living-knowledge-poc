import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.ai.models import AnswerInterpretation, QuestionDraft
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.enums import ClaimStatus, GapPriority, GapStatus, SourceType
from app.domain.evidence import Evidence
from app.domain.gap import KnowledgeGap
from app.domain.source import KnowledgeSource
from app.workflows.curation import CurationWorkflow


def run(coro):
    return asyncio.run(coro)


class FakeEntityRepository:
    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}

    async def create(self, entity: Entity) -> Entity:
        self.entities.setdefault(entity.id, entity)
        return self.entities[entity.id]

    async def get(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)

    async def find_by_name_or_alias(self, name: str, namespace: str) -> Entity | None:
        normalized = name.casefold()
        for entity in self.entities.values():
            if entity.namespace != namespace:
                continue
            if entity.canonical_name.casefold() == normalized:
                return entity
            if any(alias.casefold() == normalized for alias in entity.aliases):
                return entity
        return None


class FakeClaimRepository:
    def __init__(self) -> None:
        self.claims: dict[str, Claim] = {}
        self.evidence: dict[str, Evidence] = {}

    async def create(self, claim: Claim) -> Claim:
        self.claims.setdefault(claim.id, claim)
        return self.claims[claim.id]

    async def list_for_entity(self, entity_id: str) -> list[Claim]:
        return [
            claim
            for claim in self.claims.values()
            if claim.subject_entity_id == entity_id or claim.object_entity_id == entity_id
        ]

    async def add_evidence(self, evidence: Evidence) -> Evidence:
        self.evidence.setdefault(evidence.id, evidence)
        return self.evidence[evidence.id]


class FakeSourceRepository:
    def __init__(self) -> None:
        self.sources: dict[str, KnowledgeSource] = {}

    async def create(self, source: KnowledgeSource) -> KnowledgeSource:
        self.sources.setdefault(source.id, source)
        return self.sources[source.id]


class FakeGapRepository:
    def __init__(self) -> None:
        self.gaps: dict[str, KnowledgeGap] = {}

    async def get(self, gap_id: str) -> KnowledgeGap | None:
        return self.gaps.get(gap_id)

    async def resolve(self, gap_id: str) -> KnowledgeGap | None:
        gap = self.gaps.get(gap_id)
        if gap is None:
            return None
        resolved = gap.model_copy(update={"status": GapStatus.RESOLVED})
        self.gaps[gap_id] = resolved
        return resolved


class FakeQuestionGenerator:
    async def generate(self, gap, entity, existing_claims) -> QuestionDraft:
        return QuestionDraft(question=f"Which service currently consumes {entity.canonical_name}?")


class FakeAnswerInterpreter:
    def __init__(self, interpretation: AnswerInterpretation) -> None:
        self.interpretation = interpretation

    async def interpret(self, question, answer, gap, entity) -> AnswerInterpretation:
        return self.interpretation


def build_repositories(gap_status: GapStatus = GapStatus.OPEN, gap_type: str = "MISSING_CONSUMER"):
    entities = FakeEntityRepository()
    claims = FakeClaimRepository()
    sources = FakeSourceRepository()
    gaps = FakeGapRepository()
    entity = Entity(
        id="test:concept:scheduled-dispatch",
        entity_type="BUSINESS_CONCEPT",
        canonical_name="Scheduled Dispatch",
        namespace="test",
    )
    entities.entities[entity.id] = entity
    gaps.gaps["test:gap"] = KnowledgeGap(
        id="test:gap",
        entity_id=entity.id,
        gap_type=gap_type,
        description="The consumer is unknown.",
        priority=GapPriority.HIGH,
        status=gap_status,
    )
    return entities, claims, sources, gaps


async def with_workflow(interpretation: AnswerInterpretation, body, gap_status: GapStatus = GapStatus.OPEN, gap_type: str = "MISSING_CONSUMER"):
    entities, claims, sources, gaps = build_repositories(gap_status=gap_status, gap_type=gap_type)
    with TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "checkpoints.db"
        async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
            await checkpointer.setup()
            workflow = CurationWorkflow(
                entity_repository=entities,
                claim_repository=claims,
                source_repository=sources,
                gap_repository=gaps,
                question_generator=FakeQuestionGenerator(),
                answer_interpreter=FakeAnswerInterpreter(interpretation),
                checkpointer=checkpointer,
            )
            return await body(workflow, entities, claims, sources, gaps)


def test_workflow_loads_open_gap_and_reaches_interrupt() -> None:
    async def body(workflow, entities, claims, sources, gaps):
        result = await workflow.start("test-workflow-1", "test:gap")
        assert result["status"] == "WAITING_FOR_HUMAN"
        assert result["question"] == "Which service currently consumes Scheduled Dispatch?"

    run(with_workflow(AnswerInterpretation(can_resolve=False), body))


def test_workflow_resume_with_resolvable_answer_resolves_gap() -> None:
    async def body(workflow, entities, claims, sources, gaps):
        await workflow.start("test-workflow-2", "test:gap")
        result = await workflow.answer("test-workflow-2", "Scheduler Service")
        assert result["status"] == "RESOLVED"
        assert result["entity_id"] == "test:service:scheduler-service"
        assert gaps.gaps["test:gap"].status == GapStatus.RESOLVED

    run(
        with_workflow(
            AnswerInterpretation(can_resolve=True, entity_name="Scheduler Service", entity_type="SERVICE"),
            body,
        )
    )


def test_workflow_resume_with_unresolvable_answer_needs_review() -> None:
    async def body(workflow, entities, claims, sources, gaps):
        await workflow.start("test-workflow-3", "test:gap")
        result = await workflow.answer("test-workflow-3", "I don't know")
        assert result["status"] == "NEEDS_REVIEW"
        assert result["review_reason"] == "ANSWER_UNCLEAR"
        assert gaps.gaps["test:gap"].status == GapStatus.OPEN
        assert claims.claims == {}
        assert sources.sources == {}

    run(
        with_workflow(
            AnswerInterpretation(
                can_resolve=False,
                reason="The answer does not identify a consumer.",
            ),
            body,
        )
    )


def test_unsupported_gap_type_fails_without_writes() -> None:
    async def body(workflow, entities, claims, sources, gaps):
        await workflow.start("test-workflow-4", "test:gap")
        with pytest.raises(ValueError, match="UNSUPPORTED_GAP_TYPE"):
            await workflow.answer("test-workflow-4", "Scheduler Service")
        assert claims.claims == {}
        assert sources.sources == {}
        assert gaps.gaps["test:gap"].status == GapStatus.OPEN

    run(
        with_workflow(
            AnswerInterpretation(can_resolve=True, entity_name="Scheduler Service", entity_type="SERVICE"),
            body,
            gap_type="UNSUPPORTED",
        )
    )


def test_resolved_gap_cannot_start_new_workflow() -> None:
    async def body(workflow, entities, claims, sources, gaps):
        with pytest.raises(ValueError, match="GAP_NOT_OPEN"):
            await workflow.start("test-workflow-5", "test:gap")

    run(with_workflow(AnswerInterpretation(can_resolve=False), body, gap_status=GapStatus.RESOLVED))
