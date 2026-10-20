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
from app.assistant.service import KnowledgeAssistantService, _search_terms
from app.domain.enums import ClaimStatus, GapPriority


class FakePlanner:
    def __init__(self, response: KnowledgeQueryPlan) -> None:
        self.response = response

    async def plan(self, question: str) -> KnowledgeQueryPlan:
        return self.response


class FakeRepository:
    def __init__(self, claims: list[RetrievedClaim], gaps: list[OpenGapContext] | None = None, conflicts: list[OpenConflictContext] | None = None, candidate_claims: list[RetrievedClaim] | None = None) -> None:
        self.claims = claims
        self.gaps = gaps or []
        self.conflicts = conflicts or []
        self.candidate_claims = candidate_claims or []
        self.search_terms: list[str] = []

    async def resolve_entities(self, names: list[str], namespace: str) -> list[EntityResolution]:
        return [
            EntityResolution(
                requested_name=name,
                matches=[MatchedEntity(id="entity:one", label=name, entity_type="SERVICE", namespace=namespace)],
            )
            for name in names
        ]

    async def get_claim_context(self, **kwargs) -> list[RetrievedClaim]:
        if kwargs.get("candidate_claim_ids") is not None:
            return self.candidate_claims
        if not kwargs.get("entity_ids"):
            return []
        return self.claims

    async def search_claim_ids(self, terms: list[str], namespace: str, max_claims: int, answer_entity_types: list[str], predicates: list[str]) -> list[str]:
        self.search_terms = terms
        return [claim.claim_id for claim in self.candidate_claims]

    async def get_open_gaps(self, entity_ids: list[str]) -> list[OpenGapContext]:
        return self.gaps

    async def get_open_conflicts(self, claim_ids: list[str]) -> list[OpenConflictContext]:
        return self.conflicts


class FakeGenerator:
    def __init__(self, draft: AnswerDraft) -> None:
        self.draft = draft
        self.calls = 0
        self.context = None

    async def generate(self, question: str, context) -> AnswerDraft:
        self.calls += 1
        self.context = context
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


def test_service_question_uses_service_evidence_instead_of_document_intro() -> None:
    intro = RetrievedClaim(
        claim_id="claim:intro", subject_entity_id="entity:document", subject_name="Cedar Brief",
        subject_type="DOCUMENT", predicate="PURPOSE", object_entity_id="entity:shipments",
        object_name="shipments", claim_status=ClaimStatus.PROPOSED, confidence=0.9,
        evidence=[RetrievedEvidence(evidence_id="evidence:intro", source_id="source:file", source_type="FILE_UPLOAD", source_title="Cedar Brief", excerpt="The brief records shipments.")],
    )
    fulfillment = RetrievedClaim(
        claim_id="claim:fulfillment", subject_entity_id="entity:fulfillment",
        subject_name="Cedar Fulfillment Service", subject_type="SERVICE", predicate="WRITES_TO",
        object_entity_id="entity:shipment-db", object_name="Cedar Shipment Database",
        claim_status=ClaimStatus.PROPOSED, confidence=0.97,
        evidence=[RetrievedEvidence(evidence_id="evidence:fulfillment", source_id="source:file", source_type="FILE_UPLOAD", source_title="Cedar Brief", excerpt="It saves the allocated shipment details in Cedar Shipment Database.")],
    )
    repository = FakeRepository([intro], candidate_claims=[fulfillment])
    generator = FakeGenerator(AnswerDraft(
        answer="Cedar Fulfillment Service handles shipments.", insufficient_knowledge=False,
        cited_claim_ids=["claim:fulfillment"], cited_evidence_ids=["evidence:fulfillment"],
    ))
    assistant = service(repository, generator)
    assistant._query_planner = FakePlanner(KnowledgeQueryPlan(entity_names=[], predicates=[], direction=QueryDirection.BOTH, search_terms=["shipment"], answer_entity_types=["SERVICE"]))

    response = run(assistant.ask("Which service handles shipments?", "cedar-retail-lab"))

    assert repository.search_terms == ["shipment"]
    assert [claim.claim_id for claim in generator.context.claims] == ["claim:fulfillment"]
    assert response.answer == "Cedar Fulfillment Service handles shipments."
    assert response.knowledge_status == "PROPOSED"


def test_answer_draft_removes_internal_wrapping_from_answer() -> None:
    draft = AnswerDraft(
        answer="AnswerDraft: Cedar Fulfillment Service handles shipments. [Claim: claim:one; Evidence: evidence:one]",
        insufficient_knowledge=False,
        cited_claim_ids=["claim:one"], cited_evidence_ids=["evidence:one"],
    )

    assert draft.answer == "Cedar Fulfillment Service handles shipments."


def test_question_terms_are_generic_fallback_when_planner_omits_them() -> None:
    assert _search_terms("Which service handles shipments?", []) == ["shipment"]
    assert _search_terms("Who owns Cedar Returns Service?", []) == ["cedar", "return"]
    assert _search_terms("Where is payment data stored?", ["payment data"]) == ["payment data"]
    assert _search_terms("Which service handles shipments?", ["shipments"]) == ["shipments", "shipment"]
    assert _search_terms("Who owns Unknown Service?", ["service"]) == ["unknown"]


def test_database_question_uses_generic_claim_search() -> None:
    storage = RetrievedClaim(
        claim_id="claim:storage", subject_entity_id="entity:ledger", subject_name="Ledger Database",
        subject_type="DATABASE", predicate="PURPOSE", object_value="payment records",
        claim_status=ClaimStatus.PROPOSED, confidence=0.9,
        evidence=[RetrievedEvidence(evidence_id="evidence:storage", source_id="source:file", source_type="FILE_UPLOAD", source_title="Brief", excerpt="Payment records are stored in Ledger Database.")],
    )
    repository = FakeRepository([], candidate_claims=[storage])
    generator = FakeGenerator(AnswerDraft(answer="Ledger Database stores payment records.", insufficient_knowledge=False, cited_claim_ids=["claim:storage"], cited_evidence_ids=["evidence:storage"]))
    assistant = service(repository, generator)
    assistant._query_planner = FakePlanner(KnowledgeQueryPlan(entity_names=[], search_terms=["payment records"], answer_entity_types=["DATABASE"]))

    response = run(assistant.ask("Where are payment records stored?", "finance"))

    assert response.answer == "Ledger Database stores payment records."
    assert [claim.claim_id for claim in generator.context.claims] == ["claim:storage"]
