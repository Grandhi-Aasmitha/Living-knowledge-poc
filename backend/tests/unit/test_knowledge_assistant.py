import asyncio

import pytest

from app.ai.client import AIProviderError
from app.assistant.models import (
    AnswerDraft,
    EntityResolution,
    KnowledgeQueryPlan,
    MatchedEntity,
    OpenConflictContext,
    OpenGapContext,
    QueryDirection,
    RetrievedClaim,
    RetrievedEvidence,
)
from app.assistant.service import KnowledgeAssistantService
from app.domain.enums import ClaimStatus, GapPriority


class FakePlanner:
    def __init__(self, response: KnowledgeQueryPlan) -> None:
        self.response = response

    async def plan(self, question: str) -> KnowledgeQueryPlan:
        return self.response


class FakeRepository:
    def __init__(self, claims: list[RetrievedClaim], gaps: list[OpenGapContext] | None = None, conflicts: list[OpenConflictContext] | None = None) -> None:
        self.claims = claims
        self.gaps = gaps or []
        self.conflicts = conflicts or []

    async def resolve_entities(self, names: list[str], namespace: str) -> list[EntityResolution]:
        return [
            EntityResolution(
                requested_name=name,
                matches=[MatchedEntity(id="entity:one", label=name, entity_type="SERVICE", namespace=namespace)],
            )
            for name in names
        ]

    async def get_claim_context(self, **kwargs) -> list[RetrievedClaim]:
        return self.claims

    async def get_open_gaps(self, entity_ids: list[str]) -> list[OpenGapContext]:
        return self.gaps

    async def get_open_conflicts(self, claim_ids: list[str]) -> list[OpenConflictContext]:
        return self.conflicts


class FakeGenerator:
    def __init__(self, draft: AnswerDraft) -> None:
        self.draft = draft
        self.calls = 0

    async def generate(self, question: str, context) -> AnswerDraft:
        self.calls += 1
        return self.draft


def run(coro):
    return asyncio.run(coro)


def claim(claim_id: str = "claim:one", evidence_id: str = "evidence:one", status: ClaimStatus = ClaimStatus.CONFIRMED) -> RetrievedClaim:
    return RetrievedClaim(
        claim_id=claim_id,
        subject_entity_id="entity:team",
        subject_name="TSTVS Team",
        subject_type="TEAM",
        predicate="OWNS",
        object_entity_id="entity:one",
        object_name="Scheduler Service",
        claim_status=status,
        confidence=1.0,
        evidence=[
            RetrievedEvidence(
                evidence_id=evidence_id,
                source_id="source:human",
                source_type="HUMAN",
                source_title="Human clarification",
                excerpt="TSTVS Team",
            )
        ],
    )


def service(repository: FakeRepository, generator: FakeGenerator) -> KnowledgeAssistantService:
    return KnowledgeAssistantService(
        query_planner=FakePlanner(KnowledgeQueryPlan(entity_names=["Scheduler Service"], predicates=["OWNS"], direction=QueryDirection.INCOMING)),
        repository=repository,
        answer_generator=generator,
        max_claims=25,
        max_evidence_per_claim=2,
        max_evidence_chars=600,
        max_context_chars=12000,
    )


def test_confirmed_answer_builds_trusted_citation_metadata() -> None:
    generator = FakeGenerator(AnswerDraft(answer="TSTVS Team owns Scheduler Service.", insufficient_knowledge=False, cited_claim_ids=["claim:one"], cited_evidence_ids=["evidence:one"]))

    response = run(service(FakeRepository([claim()]), generator).ask("Who owns Scheduler Service?", "tstvs"))

    assert response.knowledge_status == "CONFIRMED"
    assert response.citations[0].source_type == "HUMAN"
    assert response.citations[0].excerpt == "TSTVS Team"


def test_proposed_answer_status_is_proposed() -> None:
    generator = FakeGenerator(AnswerDraft(answer="Proposed knowledge says it is owned.", insufficient_knowledge=False, cited_claim_ids=["claim:one"], cited_evidence_ids=["evidence:one"]))

    response = run(service(FakeRepository([claim(status=ClaimStatus.PROPOSED)]), generator).ask("Who owns Scheduler Service?", "tstvs"))

    assert response.knowledge_status == "PROPOSED"


def test_known_entity_without_claims_is_insufficient_and_skips_answer_generation() -> None:
    generator = FakeGenerator(AnswerDraft(answer="unused", insufficient_knowledge=True))

    response = run(service(FakeRepository([]), generator).ask("Who owns Scheduler Service?", "tstvs"))

    assert response.insufficient_knowledge is True
    assert response.knowledge_status == "INCOMPLETE"
    assert generator.calls == 0


def test_open_gap_makes_response_incomplete() -> None:
    generator = FakeGenerator(AnswerDraft(answer="No consumer is known.", insufficient_knowledge=False, cited_claim_ids=["claim:one"], cited_evidence_ids=["evidence:one"]))
    gap = OpenGapContext(id="gap:one", entity_id="entity:one", gap_type="MISSING_CONSUMER", description="No consumer is known.", priority=GapPriority.HIGH)

    response = run(service(FakeRepository([claim()], gaps=[gap]), generator).ask("What consumes Scheduler Service?", "tstvs"))

    assert response.knowledge_status == "INCOMPLETE"
    assert response.open_gaps == [gap]


def test_open_conflict_makes_response_conflicting() -> None:
    generator = FakeGenerator(AnswerDraft(answer="There is conflicting ownership.", insufficient_knowledge=False, cited_claim_ids=["claim:one"], cited_evidence_ids=["evidence:one"]))
    conflict = OpenConflictContext(id="conflict:one", rule_id="multiple-owners-v1", description="Multiple owners.", claim_ids=["claim:one"])

    response = run(service(FakeRepository([claim()], conflicts=[conflict]), generator).ask("Who owns Scheduler Service?", "tstvs"))

    assert response.knowledge_status == "CONFLICTING"
    assert response.open_conflicts == [conflict]


def test_hallucinated_claim_id_is_rejected() -> None:
    generator = FakeGenerator(AnswerDraft(answer="Bad citation.", insufficient_knowledge=False, cited_claim_ids=["fake-claim"], cited_evidence_ids=["evidence:one"]))

    with pytest.raises(AIProviderError):
        run(service(FakeRepository([claim()]), generator).ask("Who owns Scheduler Service?", "tstvs"))


def test_hallucinated_evidence_id_is_rejected() -> None:
    generator = FakeGenerator(AnswerDraft(answer="Bad citation.", insufficient_knowledge=False, cited_claim_ids=["claim:one"], cited_evidence_ids=["fake-evidence"]))

    with pytest.raises(AIProviderError):
        run(service(FakeRepository([claim()]), generator).ask("Who owns Scheduler Service?", "tstvs"))


def test_evidence_must_support_cited_claim() -> None:
    claims = [claim("claim:a", "evidence:a"), claim("claim:b", "evidence:b")]
    generator = FakeGenerator(AnswerDraft(answer="Bad ownership.", insufficient_knowledge=False, cited_claim_ids=["claim:a"], cited_evidence_ids=["evidence:b"]))

    with pytest.raises(AIProviderError):
        run(service(FakeRepository(claims), generator).ask("Who owns Scheduler Service?", "tstvs"))
