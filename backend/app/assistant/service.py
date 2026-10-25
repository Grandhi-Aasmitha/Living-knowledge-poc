import re

from app.ai.client import AIProviderError
from app.assistant.answer_generator import AnswerGenerator
from app.assistant.models import (
    AssistantCitation,
    AssistantResponse,
    KnowledgeContext,
    KnowledgeQueryPlan,
    KnowledgeStatus,
    MatchedEntity,
    QueryDirection,
    RetrievedClaim,
    RetrievedEvidence,
)
from app.assistant.query_planner import QueryPlanner
from app.repositories.knowledge_query_repository import KnowledgeQueryRepository


class AssistantValidationError(ValueError):
    pass


_SEARCH_STOP_WORDS = {
    "a", "about", "an", "and", "are", "by", "can", "did", "do", "does", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "the", "to", "what", "when", "where",
    "which", "who", "why", "with", "handles", "handle", "operates", "operate", "owns",
    "own", "uses", "use", "tell", "me", "team", "service", "system",
    "database", "topic", "api", "document", "table", "column", "flow", "scheduler",
}


def _search_terms(question: str, planned_terms: list[str]) -> list[str]:
    if planned_terms:
        variants: list[str] = []
        for phrase in planned_terms:
            normalized = phrase.casefold().strip()
            words = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", normalized)
            if not words or all(word in _SEARCH_STOP_WORDS for word in words):
                continue
            singular = re.sub(r"\b[a-z]{4,}\b", lambda match: _singular_word(match.group()), normalized)
            for value in (normalized, singular):
                if value not in variants:
                    variants.append(value)
        if variants:
            return variants[:10]
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", question.casefold())
    terms: list[str] = []
    for word in words:
        if word in _SEARCH_STOP_WORDS or len(word) < 4:
            continue
        word = _singular_word(word)
        if word not in terms:
            terms.append(word)
    return terms[:5]


def _singular_word(word: str) -> str:
    if word.endswith("ies") and len(word) > 5:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 4:
        return word[:-1]
    return word


class KnowledgeAssistantService:
    def __init__(
        self,
        query_planner: QueryPlanner,
        repository: KnowledgeQueryRepository,
        answer_generator: AnswerGenerator,
        max_claims: int,
        max_evidence_per_claim: int,
        max_evidence_chars: int,
        max_context_chars: int,
    ) -> None:
        self._query_planner = query_planner
        self._repository = repository
        self._answer_generator = answer_generator
        self._max_claims = max_claims
        self._max_evidence_per_claim = max_evidence_per_claim
        self._max_evidence_chars = max_evidence_chars
        self._max_context_chars = max_context_chars

    async def ask(self, question: str, namespace: str) -> AssistantResponse:
        cleaned_question = question.strip()
        if not cleaned_question:
            raise AssistantValidationError("question is required")
        if len(cleaned_question) > 1000:
            raise AssistantValidationError("question must be at most 1000 characters")

        plan = await self._query_planner.plan(cleaned_question)
        resolutions = await self._repository.resolve_entities(plan.entity_names, namespace)
        missing = [resolution.requested_name for resolution in resolutions if not resolution.matches]
        ambiguous = [resolution for resolution in resolutions if len(resolution.matches) > 1]

        if ambiguous:
            ambiguous_names = ", ".join(resolution.requested_name for resolution in ambiguous)
            return self._insufficient_response(
                question=cleaned_question,
                answer=f"I found multiple matching entities for {ambiguous_names}. Please ask with more specificity.",
                matched_entities=[match for resolution in resolutions for match in resolution.matches],
            )

        matched_entities = [resolution.matches[0] for resolution in resolutions if resolution.matches]
        entity_ids = [entity.id for entity in matched_entities]
        direct_claims = (
            await self._repository.get_claim_context(
                entity_ids=entity_ids,
                predicates=plan.predicates,
                direction=plan.direction,
                namespace=namespace,
                max_claims=self._max_claims,
                max_evidence_per_claim=self._max_evidence_per_claim,
            )
            if entity_ids else []
        )
        terms = _search_terms(cleaned_question, plan.search_terms)
        candidate_ids = await self._repository.search_claim_ids(
            terms, namespace, self._max_claims, plan.answer_entity_types, plan.predicates
        ) if terms else []
        candidate_claims = []
        if candidate_ids:
            found = await self._repository.get_claim_context(
                entity_ids=[], predicates=[], direction=QueryDirection.BOTH, namespace=namespace,
                max_claims=self._max_claims, max_evidence_per_claim=self._max_evidence_per_claim,
                candidate_claim_ids=candidate_ids,
            )
            by_id = {claim.claim_id: claim for claim in found}
            candidate_claims = [by_id[claim_id] for claim_id in candidate_ids if claim_id in by_id]
        preferred = candidate_claims if plan.answer_entity_types else direct_claims
        secondary = direct_claims if plan.answer_entity_types else candidate_claims
        claims = list({claim.claim_id: claim for claim in [*preferred, *secondary]}.values())[:self._max_claims]
        missing_answer_types = [
            entity_type for entity_type in plan.answer_entity_types
            if not any(claim.subject_type == entity_type or claim.object_type == entity_type for claim in claims)
        ]
        if missing_answer_types and claims:
            bridge_entity_ids = list(dict.fromkeys(
                entity_id
                for claim in claims
                for entity_id in (claim.subject_entity_id, claim.object_entity_id)
                if entity_id is not None
            ))
            remaining = self._max_claims - len(claims)
            if bridge_entity_ids and remaining > 0:
                related_claims = await self._repository.get_claim_context(
                    entity_ids=bridge_entity_ids,
                    predicates=[],
                    direction=QueryDirection.BOTH,
                    namespace=namespace,
                    max_claims=remaining,
                    max_evidence_per_claim=self._max_evidence_per_claim,
                    answer_entity_types=missing_answer_types,
                )
                claims = list({claim.claim_id: claim for claim in [*claims, *related_claims]}.values())[:self._max_claims]
        if missing and not claims:
            return self._insufficient_response(
                question=cleaned_question,
                answer=f"I couldn't find {', '.join(missing)} in the current knowledge base.",
                matched_entities=matched_entities,
            )
        for claim in claims:
            if claim.subject_entity_id not in entity_ids:
                matched_entities.append(MatchedEntity(
                    id=claim.subject_entity_id, label=claim.subject_name,
                    entity_type=claim.subject_type, namespace=namespace,
                ))
                entity_ids.append(claim.subject_entity_id)
            if claim.object_entity_id and claim.object_entity_id not in entity_ids:
                entity_ids.append(claim.object_entity_id)
        open_gaps = await self._repository.get_open_gaps(entity_ids)
        open_conflicts = await self._repository.get_open_conflicts([claim.claim_id for claim in claims])
        full_context = KnowledgeContext(
            matched_entities=matched_entities,
            claims=claims,
            open_gaps=open_gaps,
            open_conflicts=open_conflicts,
            truncated=False,
        )
        bounded_context = self._bound_context(full_context)

        if not bounded_context.claims:
            return AssistantResponse(
                question=cleaned_question,
                answer="I don't have enough source-backed knowledge to answer that.",
                insufficient_knowledge=True,
                knowledge_status=KnowledgeStatus.INCOMPLETE,
                matched_entities=matched_entities,
                citations=[],
                open_gaps=bounded_context.open_gaps,
                open_conflicts=bounded_context.open_conflicts,
                context_truncated=bounded_context.truncated,
            )

        draft = await self._answer_generator.generate(cleaned_question, bounded_context)
        self._validate_citations(draft.cited_claim_ids, draft.cited_evidence_ids, bounded_context)
        citations = self._build_citations(draft.cited_claim_ids, draft.cited_evidence_ids, bounded_context)
        return AssistantResponse(
            question=cleaned_question,
            answer=draft.answer,
            insufficient_knowledge=draft.insufficient_knowledge,
            knowledge_status=self._knowledge_status(draft.insufficient_knowledge, citations, bounded_context),
            matched_entities=matched_entities,
            citations=citations,
            open_gaps=bounded_context.open_gaps,
            open_conflicts=bounded_context.open_conflicts,
            context_truncated=bounded_context.truncated,
        )

    def _insufficient_response(self, question: str, answer: str, matched_entities: list[MatchedEntity]) -> AssistantResponse:
        return AssistantResponse(
            question=question,
            answer=answer,
            insufficient_knowledge=True,
            knowledge_status=KnowledgeStatus.INCOMPLETE,
            matched_entities=matched_entities,
            citations=[],
            open_gaps=[],
            open_conflicts=[],
            context_truncated=False,
        )

    def _bound_context(self, context: KnowledgeContext) -> KnowledgeContext:
        truncated = context.truncated
        used_chars = 0
        bounded_claims: list[RetrievedClaim] = []
        for claim in context.claims:
            bounded_evidence: list[RetrievedEvidence] = []
            for evidence in claim.evidence[: self._max_evidence_per_claim]:
                excerpt = evidence.excerpt
                if excerpt is not None and len(excerpt) > self._max_evidence_chars:
                    excerpt = excerpt[: self._max_evidence_chars]
                    truncated = True
                evidence_copy = evidence.model_copy(update={"excerpt": excerpt})
                evidence_chars = len(evidence_copy.model_dump_json())
                if used_chars + evidence_chars > self._max_context_chars:
                    truncated = True
                    break
                used_chars += evidence_chars
                bounded_evidence.append(evidence_copy)
            if not bounded_evidence:
                truncated = True
                break
            claim_copy = claim.model_copy(update={"evidence": bounded_evidence})
            claim_chars = len(claim_copy.model_dump_json())
            if used_chars + claim_chars > self._max_context_chars:
                truncated = True
                break
            used_chars += claim_chars
            bounded_claims.append(claim_copy)
        if len(bounded_claims) < len(context.claims):
            truncated = True
        return context.model_copy(update={"claims": bounded_claims, "truncated": truncated})

    def _validate_citations(self, claim_ids: list[str], evidence_ids: list[str], context: KnowledgeContext) -> None:
        claims_by_id = {claim.claim_id: claim for claim in context.claims}
        evidence_to_claim_ids: dict[str, set[str]] = {}
        for claim in context.claims:
            for evidence in claim.evidence:
                evidence_to_claim_ids.setdefault(evidence.evidence_id, set()).add(claim.claim_id)

        unknown_claims = [claim_id for claim_id in claim_ids if claim_id not in claims_by_id]
        if unknown_claims:
            raise AIProviderError("Assistant returned an unknown claim citation")
        unknown_evidence = [evidence_id for evidence_id in evidence_ids if evidence_id not in evidence_to_claim_ids]
        if unknown_evidence:
            raise AIProviderError("Assistant returned an unknown evidence citation")
        if claim_ids and evidence_ids:
            cited_claims = set(claim_ids)
            for evidence_id in evidence_ids:
                if evidence_to_claim_ids[evidence_id].isdisjoint(cited_claims):
                    raise AIProviderError("Assistant returned evidence that does not support a cited claim")

    def _build_citations(self, claim_ids: list[str], evidence_ids: list[str], context: KnowledgeContext) -> list[AssistantCitation]:
        cited_claims = set(claim_ids)
        cited_evidence = set(evidence_ids)
        citations: list[AssistantCitation] = []
        for claim in context.claims:
            if claim.claim_id not in cited_claims:
                continue
            for evidence in claim.evidence:
                if evidence.evidence_id not in cited_evidence:
                    continue
                citations.append(
                    AssistantCitation(
                        claim_id=claim.claim_id,
                        claim_status=claim.claim_status,
                        predicate=claim.predicate,
                        evidence_id=evidence.evidence_id,
                        source_type=evidence.source_type,
                        source_title=evidence.source_title,
                        excerpt=evidence.excerpt,
                        locator=evidence.locator,
                        document_title=evidence.document_title,
                        document_version=evidence.document_version,
                        source_url=evidence.source_url,
                        subject_name=claim.subject_name,
                        object_name=claim.object_name,
                        object_value=claim.object_value,
                    )
                )
        return citations

    def _knowledge_status(self, insufficient: bool, citations: list[AssistantCitation], context: KnowledgeContext) -> KnowledgeStatus:
        if context.open_conflicts:
            return KnowledgeStatus.CONFLICTING
        if insufficient or context.open_gaps:
            return KnowledgeStatus.INCOMPLETE
        if citations and all(citation.claim_status == "CONFIRMED" for citation in citations):
            return KnowledgeStatus.CONFIRMED
        return KnowledgeStatus.PROPOSED
