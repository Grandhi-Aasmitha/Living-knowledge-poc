from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.ai.answer_interpreter import AnswerInterpreter
from app.ai.models import AnswerInterpretation, ClaimCandidate
from app.ai.question_generator import QuestionGenerator
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.enums import ClaimStatus, EntityStatus, SourceType
from app.domain.evidence import Evidence
from app.domain.gap import KnowledgeGap
from app.domain.identifiers import stable_entity_id
from app.domain.source import KnowledgeSource
from app.repositories.claim_repository import ClaimRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.gap_repository import GapRepository
from app.repositories.source_repository import SourceRepository


WorkflowStatus = Literal["WAITING_FOR_HUMAN", "RESOLVED", "NEEDS_REVIEW", "ERROR"]


class CurationState(TypedDict, total=False):
    workflow_id: str
    gap_id: str
    gap_type: str
    gap_entity_id: str
    gap_entity_name: str
    namespace: str
    question: str
    engineer_answer: str
    interpretation: dict[str, Any]
    claim_candidate: dict[str, Any]
    resulting_entity_id: str
    resulting_claim_id: str
    status: WorkflowStatus
    error: str
    _gap: dict[str, Any]
    _entity: dict[str, Any]
    _existing_claims: list[dict[str, Any]]


class CurationWorkflow:
    def __init__(
        self,
        entity_repository: EntityRepository,
        claim_repository: ClaimRepository,
        source_repository: SourceRepository,
        gap_repository: GapRepository,
        question_generator: QuestionGenerator,
        answer_interpreter: AnswerInterpreter,
        checkpointer: Any,
    ) -> None:
        self._entity_repository = entity_repository
        self._claim_repository = claim_repository
        self._source_repository = source_repository
        self._gap_repository = gap_repository
        self._question_generator = question_generator
        self._answer_interpreter = answer_interpreter
        self._graph = self._build_graph(checkpointer)

    async def start(self, workflow_id: str, gap_id: str) -> dict[str, Any]:
        config = {"configurable": {"thread_id": workflow_id}}
        result = await self._graph.ainvoke(
            {"workflow_id": workflow_id, "gap_id": gap_id},
            config=config,
        )
        return self._response_from_result(result)

    async def answer(self, workflow_id: str, answer: str) -> dict[str, Any]:
        config = {"configurable": {"thread_id": workflow_id}}
        state = await self._graph.aget_state(config)
        if not state.next:
            raise ValueError(f"WORKFLOW_NOT_WAITING:{workflow_id}")

        result = await self._graph.ainvoke(Command(resume=answer), config=config)
        return self._response_from_result(result)

    async def has_checkpoint(self, workflow_id: str) -> bool:
        config = {"configurable": {"thread_id": workflow_id}}
        state = await self._graph.aget_state(config)
        return bool(state.values or state.next)

    async def persist_knowledge_for_retry(self, state: CurationState) -> CurationState:
        return await self._persist_knowledge(state)

    def _build_graph(self, checkpointer: Any) -> Any:
        graph = StateGraph(CurationState)
        graph.add_node("load_context", self._load_context)
        graph.add_node("generate_question", self._generate_question)
        graph.add_node("wait_for_human", self._wait_for_human)
        graph.add_node("interpret_answer", self._interpret_answer)
        graph.add_node("mark_needs_review", self._mark_needs_review)
        graph.add_node("build_claim_candidate", self._build_claim_candidate)
        graph.add_node("persist_knowledge", self._persist_knowledge)

        graph.add_edge(START, "load_context")
        graph.add_edge("load_context", "generate_question")
        graph.add_edge("generate_question", "wait_for_human")
        graph.add_edge("wait_for_human", "interpret_answer")
        graph.add_conditional_edges(
            "interpret_answer",
            self._route_after_interpretation,
            {
                "needs_review": "mark_needs_review",
                "persist": "build_claim_candidate",
            },
        )
        graph.add_edge("mark_needs_review", END)
        graph.add_edge("build_claim_candidate", "persist_knowledge")
        graph.add_edge("persist_knowledge", END)
        return graph.compile(checkpointer=checkpointer)

    async def _load_context(self, state: CurationState) -> CurationState:
        gap_id = state["gap_id"]
        gap = await self._gap_repository.get(gap_id)
        if gap is None:
            raise ValueError(f"GAP_NOT_FOUND:{gap_id}")
        if gap.status != "OPEN":
            raise ValueError(f"GAP_NOT_OPEN:{gap_id}")

        entity = await self._entity_repository.get(gap.entity_id)
        if entity is None:
            raise ValueError(f"RELATED_ENTITY_NOT_FOUND:{gap.entity_id}")

        existing_claims = await self._claim_repository.list_for_entity(entity.id)
        return {
            **state,
            "gap_type": gap.gap_type,
            "gap_entity_id": entity.id,
            "gap_entity_name": entity.canonical_name,
            "namespace": entity.namespace,
            "_gap": gap.model_dump(mode="json"),
            "_entity": entity.model_dump(mode="json"),
            "_existing_claims": [claim.model_dump(mode="json") for claim in existing_claims],
        }

    async def _generate_question(self, state: CurationState) -> CurationState:
        gap = self._gap_from_state(state)
        entity = self._entity_from_state(state)
        existing_claims = [Claim(**claim) for claim in state.get("_existing_claims", [])]
        draft = await self._question_generator.generate(gap, entity, existing_claims)
        return {**state, "question": draft.question, "status": "WAITING_FOR_HUMAN"}

    async def _wait_for_human(self, state: CurationState) -> CurationState:
        answer = interrupt(
            {
                "workflow_id": state["workflow_id"],
                "gap_id": state["gap_id"],
                "gap_type": state["gap_type"],
                "entity_name": state["gap_entity_name"],
                "question": state["question"],
                "status": "WAITING_FOR_HUMAN",
            }
        )
        return {**state, "engineer_answer": str(answer).strip()}

    async def _interpret_answer(self, state: CurationState) -> CurationState:
        interpretation = await self._answer_interpreter.interpret(
            question=state["question"],
            answer=state["engineer_answer"],
            gap=self._gap_from_state(state),
            entity=self._entity_from_state(state),
        )
        return {**state, "interpretation": interpretation.model_dump(mode="json")}

    def _route_after_interpretation(self, state: CurationState) -> str:
        interpretation = AnswerInterpretation(**state["interpretation"])
        if not interpretation.can_resolve:
            return "needs_review"
        return "persist"

    async def _mark_needs_review(self, state: CurationState) -> CurationState:
        return {**state, "status": "NEEDS_REVIEW"}

    async def _build_claim_candidate(self, state: CurationState) -> CurationState:
        if state["gap_type"] != "MISSING_CONSUMER":
            raise ValueError(f"UNSUPPORTED_GAP_TYPE:{state['gap_type']}")

        interpretation = AnswerInterpretation(**state["interpretation"])
        if interpretation.entity_name is None or interpretation.entity_type is None:
            raise ValueError("UNRESOLVED_INTERPRETATION")

        candidate_entity_id = stable_entity_id(
            namespace=state["namespace"],
            entity_type=interpretation.entity_type,
            canonical_name=interpretation.entity_name,
        )
        candidate = ClaimCandidate(
            subject_entity_id=candidate_entity_id,
            predicate="CONSUMES",
            object_entity_id=state["gap_entity_id"],
            confidence=1.0,
        )
        return {**state, "claim_candidate": candidate.model_dump(mode="json")}

    async def _persist_knowledge(self, state: CurationState) -> CurationState:
        interpretation = AnswerInterpretation(**state["interpretation"])
        candidate = ClaimCandidate(**state["claim_candidate"])
        workflow_id = state["workflow_id"]
        now = datetime.now(UTC)

        if interpretation.entity_name is None or interpretation.entity_type is None:
            raise ValueError("UNRESOLVED_INTERPRETATION")

        entity = await self._entity_repository.find_by_name_or_alias(
            name=interpretation.entity_name,
            namespace=state["namespace"],
        )
        if entity is None:
            entity = await self._entity_repository.create(
                Entity(
                    id=candidate.subject_entity_id,
                    entity_type=interpretation.entity_type,
                    canonical_name=interpretation.entity_name,
                    namespace=state["namespace"],
                    status=EntityStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                )
            )

        source = await self._source_repository.create(
            KnowledgeSource(
                id=f"human:curation:{workflow_id}",
                source_type=SourceType.HUMAN,
                title=f"Human clarification for {state['gap_id']}",
                external_id=workflow_id,
                version="1",
                created_at=now,
            )
        )
        claim = await self._claim_repository.create(
            Claim(
                id=f"curation:claim:{workflow_id}",
                subject_entity_id=entity.id,
                predicate=candidate.predicate,
                object_entity_id=candidate.object_entity_id,
                confidence=1.0,
                status=ClaimStatus.CONFIRMED,
                created_at=now,
                updated_at=now,
            )
        )
        await self._claim_repository.add_evidence(
            Evidence(
                id=f"curation:evidence:{workflow_id}",
                claim_id=claim.id,
                source_id=source.id,
                excerpt=state["engineer_answer"],
                locator=f"Question: {state['question']}",
                created_at=now,
            )
        )
        await self._gap_repository.resolve(state["gap_id"])

        return {
            **state,
            "resulting_entity_id": entity.id,
            "resulting_claim_id": claim.id,
            "status": "RESOLVED",
        }

    def _response_from_result(self, result: dict[str, Any]) -> dict[str, Any]:
        interrupts = result.get("__interrupt__")
        if interrupts:
            payload = interrupts[0].value
            return dict(payload)
        return {
            "workflow_id": result.get("workflow_id"),
            "gap_id": result.get("gap_id"),
            "status": result.get("status"),
            "entity_id": result.get("resulting_entity_id"),
            "claim_id": result.get("resulting_claim_id"),
        }

    def _gap_from_state(self, state: CurationState) -> KnowledgeGap:
        return KnowledgeGap(**state["_gap"])

    def _entity_from_state(self, state: CurationState) -> Entity:
        return Entity(**state["_entity"])
