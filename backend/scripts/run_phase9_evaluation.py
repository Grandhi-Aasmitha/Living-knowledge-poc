import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

import yaml

from app.assistant.answer_generator import AnswerGenerator
from app.assistant.models import AnswerDraft, AssistantResponse, KnowledgeQueryPlan, QueryDirection
from app.assistant.query_planner import QueryPlanner
from app.assistant.service import KnowledgeAssistantService
from app.config import REPOSITORY_ROOT, get_settings
from app.conflicts.models import KnowledgeConflict
from app.db.neo4j import Neo4jClient
from app.db.schema import ensure_schema
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.enums import ClaimStatus, ConflictStatus, GapPriority, GapStatus, SourceType
from app.domain.evidence import Evidence
from app.domain.gap import KnowledgeGap
from app.domain.source import KnowledgeSource
from app.evaluation.models import GoldenCase
from app.repositories.claim_repository import ClaimRepository
from app.repositories.conflict_repository import ConflictRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.gap_repository import GapRepository
from app.repositories.knowledge_query_repository import KnowledgeQueryRepository
from app.repositories.source_repository import SourceRepository

NAMESPACE = "phase9-eval"
T = TypeVar("T")


class DeterministicEvaluationAIClient:
    async def generate_structured(self, prompt: str, response_model: type[Any]) -> Any:
        if response_model is KnowledgeQueryPlan:
            return self._plan(prompt)
        return self._answer(prompt)

    def _plan(self, prompt: str) -> KnowledgeQueryPlan:
        if "Who owns Eval App" in prompt:
            return KnowledgeQueryPlan(entity_names=["Eval App"], predicates=["OWNS"], direction=QueryDirection.INCOMING)
        if "Who owns Eval Service" in prompt:
            return KnowledgeQueryPlan(entity_names=["Eval Service"], predicates=["OWNS"], direction=QueryDirection.INCOMING)
        if "What does Eval Service produce" in prompt:
            return KnowledgeQueryPlan(entity_names=["Eval Service"], predicates=["PRODUCES", "PUBLISHES_TO"], direction=QueryDirection.OUTGOING)
        if "What consumes Eval Topic" in prompt:
            return KnowledgeQueryPlan(entity_names=["Eval Topic"], predicates=["CONSUMES", "RECEIVES_FROM"], direction=QueryDirection.INCOMING)
        if "Tell me about Eval Service" in prompt:
            return KnowledgeQueryPlan(entity_names=["Eval Service"], predicates=[], direction=QueryDirection.BOTH)
        if "What does Eval Consumer call" in prompt:
            return KnowledgeQueryPlan(entity_names=["Eval Consumer"], predicates=["CALLS"], direction=QueryDirection.OUTGOING)
        if "What database does Eval Service write to" in prompt:
            return KnowledgeQueryPlan(entity_names=["Eval Service"], predicates=["WRITES_TO"], direction=QueryDirection.OUTGOING)
        if "What consumes Eval Gap Topic" in prompt:
            return KnowledgeQueryPlan(entity_names=["Eval Gap Topic"], predicates=["CONSUMES", "RECEIVES_FROM"], direction=QueryDirection.INCOMING)
        if "Who owns Eval Conflict Service" in prompt:
            return KnowledgeQueryPlan(entity_names=["Eval Conflict Service"], predicates=["OWNS"], direction=QueryDirection.INCOMING)
        return KnowledgeQueryPlan(entity_names=["Unknown"], predicates=[], direction=QueryDirection.BOTH)

    def _answer(self, prompt: str) -> AnswerDraft:
        citations = {
            "phase9-eval:claim:owns": "phase9-eval:evidence:owns",
            "phase9-eval:claim:produces": "phase9-eval:evidence:produces",
            "phase9-eval:claim:consumes": "phase9-eval:evidence:consumes",
            "phase9-eval:claim:proposed-call": "phase9-eval:evidence:proposed-call",
            "phase9-eval:claim:conflict-a": "phase9-eval:evidence:conflict-a",
            "phase9-eval:claim:conflict-b": "phase9-eval:evidence:conflict-b",
        }
        cited_claims = [claim_id for claim_id in citations if claim_id in prompt]
        cited_evidence = [citations[claim_id] for claim_id in cited_claims]
        if not cited_claims:
            return AnswerDraft(answer="I don't have enough source-backed knowledge to answer that.", insufficient_knowledge=True)
        return AnswerDraft(
            answer="This answer is supported by the cited source-backed knowledge.",
            insufficient_knowledge=False,
            cited_claim_ids=cited_claims,
            cited_evidence_ids=cited_evidence,
        )


async def cleanup(client: Neo4jClient) -> None:
    async with client.session() as session:
        await session.run("MATCH (conflict:KnowledgeConflict {namespace: $namespace}) DETACH DELETE conflict", namespace=NAMESPACE)
        await session.run("MATCH (gap:KnowledgeGap) WHERE gap.id STARTS WITH 'phase9-eval:' DETACH DELETE gap")
        await session.run("MATCH (evidence:Evidence) WHERE evidence.id STARTS WITH 'phase9-eval:' DETACH DELETE evidence")
        await session.run("MATCH (claim:Claim) WHERE claim.id STARTS WITH 'phase9-eval:' DETACH DELETE claim")
        await session.run("MATCH (source:KnowledgeSource) WHERE source.id STARTS WITH 'phase9-eval:' DETACH DELETE source")
        await session.run("MATCH (entity:Entity {namespace: $namespace}) DETACH DELETE entity", namespace=NAMESPACE)


async def create_fixture(client: Neo4jClient) -> None:
    entity_repository = EntityRepository(client)
    for item in [
        Entity(id="phase9-eval:team:eval-team", entity_type="TEAM", canonical_name="Eval Team", namespace=NAMESPACE),
        Entity(id="phase9-eval:team:team-alpha", entity_type="TEAM", canonical_name="Team Alpha", namespace=NAMESPACE),
        Entity(id="phase9-eval:team:team-beta", entity_type="TEAM", canonical_name="Team Beta", namespace=NAMESPACE),
        Entity(id="phase9-eval:service:eval-service", entity_type="SERVICE", canonical_name="Eval Service", namespace=NAMESPACE, aliases=["Eval App"]),
        Entity(id="phase9-eval:service:eval-consumer", entity_type="SERVICE", canonical_name="Eval Consumer", namespace=NAMESPACE),
        Entity(id="phase9-eval:service:eval-conflict-service", entity_type="SERVICE", canonical_name="Eval Conflict Service", namespace=NAMESPACE),
        Entity(id="phase9-eval:topic:eval-topic", entity_type="TOPIC", canonical_name="Eval Topic", namespace=NAMESPACE),
        Entity(id="phase9-eval:topic:eval-gap-topic", entity_type="TOPIC", canonical_name="Eval Gap Topic", namespace=NAMESPACE),
        Entity(id="phase9-eval:database:eval-database", entity_type="DATABASE", canonical_name="Eval Database", namespace=NAMESPACE),
    ]:
        await entity_repository.create(item)
    await SourceRepository(client).create(KnowledgeSource(id="phase9-eval:source", source_type=SourceType.SYSTEM, title="Phase 9 Golden Fixture"))
    for claim, evidence_id, excerpt in [
        (Claim(id="phase9-eval:claim:owns", subject_entity_id="phase9-eval:team:eval-team", predicate="OWNS", object_entity_id="phase9-eval:service:eval-service", status=ClaimStatus.CONFIRMED, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)), "phase9-eval:evidence:owns", "Eval Team owns Eval Service."),
        (Claim(id="phase9-eval:claim:produces", subject_entity_id="phase9-eval:service:eval-service", predicate="PRODUCES", object_entity_id="phase9-eval:topic:eval-topic", status=ClaimStatus.CONFIRMED, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)), "phase9-eval:evidence:produces", "Eval Service produces Eval Topic."),
        (Claim(id="phase9-eval:claim:consumes", subject_entity_id="phase9-eval:service:eval-consumer", predicate="CONSUMES", object_entity_id="phase9-eval:topic:eval-topic", status=ClaimStatus.CONFIRMED, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)), "phase9-eval:evidence:consumes", "Eval Consumer consumes Eval Topic."),
        (Claim(id="phase9-eval:claim:proposed-call", subject_entity_id="phase9-eval:service:eval-consumer", predicate="CALLS", object_entity_id="phase9-eval:service:eval-service", status=ClaimStatus.PROPOSED, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)), "phase9-eval:evidence:proposed-call", "Eval Consumer calls Eval Service."),
        (Claim(id="phase9-eval:claim:conflict-a", subject_entity_id="phase9-eval:team:team-alpha", predicate="OWNS", object_entity_id="phase9-eval:service:eval-conflict-service", status=ClaimStatus.CONFIRMED, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)), "phase9-eval:evidence:conflict-a", "Team Alpha owns Eval Conflict Service."),
        (Claim(id="phase9-eval:claim:conflict-b", subject_entity_id="phase9-eval:team:team-beta", predicate="OWNS", object_entity_id="phase9-eval:service:eval-conflict-service", status=ClaimStatus.PROPOSED, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)), "phase9-eval:evidence:conflict-b", "Team Beta owns Eval Conflict Service."),
    ]:
        await ClaimRepository(client).create(claim)
        await ClaimRepository(client).add_evidence(Evidence(id=evidence_id, claim_id=claim.id, source_id="phase9-eval:source", excerpt=excerpt))
    await GapRepository(client).create(
        KnowledgeGap(
            id="phase9-eval:gap:missing-consumer",
            entity_id="phase9-eval:topic:eval-gap-topic",
            gap_type="MISSING_CONSUMER",
            description="No consumer is currently known for Eval Gap Topic.",
            priority=GapPriority.HIGH,
            status=GapStatus.OPEN,
        )
    )
    await ConflictRepository(client).create(
        KnowledgeConflict(id="phase9-eval:conflict:owners", rule_id="multiple-owners-v1", namespace=NAMESPACE, description="Multiple owners for Eval Conflict Service.", status=ConflictStatus.OPEN),
        ["phase9-eval:claim:conflict-a", "phase9-eval:claim:conflict-b"],
    )


def load_cases() -> list[GoldenCase]:
    path = REPOSITORY_ROOT / "evaluation" / "phase9_golden.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [GoldenCase(**item) for item in data["cases"]]


def build_assistant(client: Neo4jClient) -> KnowledgeAssistantService:
    ai_client = DeterministicEvaluationAIClient()
    return KnowledgeAssistantService(
        query_planner=QueryPlanner(ai_client),
        repository=KnowledgeQueryRepository(client),
        answer_generator=AnswerGenerator(ai_client),
        max_claims=25,
        max_evidence_per_claim=2,
        max_evidence_chars=600,
        max_context_chars=12000,
    )


def evaluate_case(case: GoldenCase, response: AssistantResponse) -> tuple[bool, int, int, bool, bool]:
    returned_claim_ids = {citation.claim_id for citation in response.citations}
    matched_entity_ids = {entity.id for entity in response.matched_entities}
    required_hits = len(set(case.required_claim_ids) & returned_claim_ids)
    required_total = len(case.required_claim_ids)
    passed = True
    passed = passed and set(case.expected_entity_ids).issubset(matched_entity_ids)
    passed = passed and set(case.required_claim_ids).issubset(returned_claim_ids)
    passed = passed and set(case.forbidden_claim_ids).isdisjoint(returned_claim_ids)
    passed = passed and response.insufficient_knowledge == case.expect_insufficient_knowledge
    passed = passed and response.knowledge_status == case.expected_knowledge_status
    citation_valid = all(citation.evidence_id for citation in response.citations)
    unsupported_refusal = True
    if case.expect_insufficient_knowledge:
        unsupported_refusal = response.insufficient_knowledge and not response.citations
    return passed, required_hits, required_total, citation_valid, unsupported_refusal


async def main() -> None:
    settings = get_settings()
    client = Neo4jClient(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password, settings.neo4j_database)
    if not await client.ping():
        print("Neo4j is unavailable; cannot run Phase 9 evaluation.")
        await client.close()
        raise SystemExit(1)
    try:
        await ensure_schema(client)
        await cleanup(client)
        await create_fixture(client)
        assistant = build_assistant(client)
        cases = load_cases()
        passed_cases = 0
        required_hits = 0
        required_total = 0
        valid_citations = 0
        unsupported_refusals = 0
        insufficient_total = 0
        for case in cases:
            response = await assistant.ask(case.question, case.namespace)
            passed, hits, total, citation_valid, unsupported_refusal = evaluate_case(case, response)
            required_hits += hits
            required_total += total
            valid_citations += 1 if citation_valid else 0
            if case.expect_insufficient_knowledge:
                insufficient_total += 1
                unsupported_refusals += 1 if unsupported_refusal else 0
            if passed:
                passed_cases += 1
            print(f"{case.id}: {'PASS' if passed else 'FAIL'}")
        total_cases = len(cases)
        print(f"total_cases={total_cases}")
        print(f"passed_cases={passed_cases}")
        print(f"failed_cases={total_cases - passed_cases}")
        print(f"required_claim_recall={required_hits / required_total if required_total else 1.0:.3f}")
        print(f"citation_validity_rate={valid_citations / total_cases if total_cases else 1.0:.3f}")
        print(f"unsupported_refusal_rate={unsupported_refusals / insufficient_total if insufficient_total else 1.0:.3f}")
    finally:
        await cleanup(client)
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
