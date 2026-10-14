import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Protocol

from app.ai.client import AIProviderError, StructuredAIClient
from app.ai.entity_resolution_models import (
    EntityResolutionAction,
    EntityResolutionCandidate,
    EntityResolutionDecision,
)
from app.ai.extraction_models import ExtractedEntity
from app.ai.prompts import get_entity_resolution_prompt
from app.domain.entity import Entity


_GENERIC_TYPE_WORDS = {
    "api",
    "app",
    "application",
    "column",
    "concept",
    "database",
    "db",
    "document",
    "external",
    "flow",
    "scheduler",
    "service",
    "system",
    "table",
    "team",
    "topic",
}

_COMPATIBLE_TYPE_GROUPS = (
    {"SYSTEM", "SERVICE", "API", "SCHEDULER", "EXTERNAL_SYSTEM"},
    {"DATABASE", "TABLE", "COLUMN"},
    {"TOPIC", "FLOW", "BUSINESS_CONCEPT"},
)


@dataclass(frozen=True)
class EntityResolutionResult:
    entity: Entity | None
    created: bool = False
    needs_review: bool = False
    reason: str | None = None
    alias_learned: bool = False
    candidates: list[EntityResolutionCandidate] = field(default_factory=list)
    confidence: float = 1.0


class EntityResolutionRepository(Protocol):
    async def list_active_for_resolution(self, namespace: str, entity_types: list[str]) -> list[Entity]:
        ...

    async def get(self, entity_id: str) -> Entity | None:
        ...

class EntityResolver:
    def __init__(
        self,
        ai_client: StructuredAIClient,
        entity_repository: EntityResolutionRepository,
        auto_match_threshold: float = 0.9,
        max_candidates: int = 5,
    ) -> None:
        self._ai_client = ai_client
        self._entity_repository = entity_repository
        self._auto_match_threshold = auto_match_threshold
        self._max_candidates = max_candidates

    async def resolve(
        self,
        extracted: ExtractedEntity,
        namespace: str,
        document_context: str,
    ) -> EntityResolutionResult:
        compatible_types = _compatible_types(extracted.entity_type)
        existing_entities = await self._entity_repository.list_active_for_resolution(
            namespace=namespace,
            entity_types=sorted(compatible_types),
        )
        candidates = _rank_candidates(extracted, existing_entities, self._max_candidates)
        if not candidates:
            return EntityResolutionResult(entity=None, created=True)
        if len(candidates) == 1:
            only_candidate = candidates[0]
            existing = next(entity for entity in existing_entities if entity.id == only_candidate.entity_id)
            if existing.entity_type == extracted.entity_type and _has_exact_label(extracted.name, existing):
                return EntityResolutionResult(entity=existing)

        decision = await self._ai_client.generate_structured(
            self._build_prompt(extracted, namespace, document_context, candidates),
            EntityResolutionDecision,
        )
        if decision.action == EntityResolutionAction.CREATE:
            if decision.confidence < self._auto_match_threshold or any(_has_exact_label(extracted.name, entity) for entity in existing_entities):
                return EntityResolutionResult(entity=None, needs_review=True, candidates=candidates, confidence=decision.confidence, reason="Uncertain new entity or name already assigned")
            return EntityResolutionResult(entity=None, created=True, reason=decision.reason, candidates=candidates, confidence=decision.confidence)
        if decision.action == EntityResolutionAction.NEEDS_REVIEW:
            return EntityResolutionResult(entity=None, needs_review=True, reason=decision.reason, candidates=candidates, confidence=decision.confidence)

        candidates_by_id = {candidate.entity_id: candidate for candidate in candidates}
        matched_id = decision.matched_entity_id or ""
        if matched_id not in candidates_by_id:
            raise AIProviderError("Entity resolver returned an unknown candidate")
        if decision.confidence < self._auto_match_threshold:
            return EntityResolutionResult(
                entity=None,
                needs_review=True,
                reason="Candidate match confidence is below the automatic resolution threshold",
                candidates=candidates,
                confidence=decision.confidence,
            )

        matched = await self._entity_repository.get(matched_id)
        if matched is None or matched.namespace != namespace or matched.status != "ACTIVE" or matched.entity_type not in compatible_types:
            raise AIProviderError("Entity resolver selected a candidate that is no longer available in this namespace")
        conflicting_label_ids = {
            entity.id
            for entity in existing_entities
            if entity.id != matched.id and _has_exact_label(extracted.name, entity)
        }
        if conflicting_label_ids:
            return EntityResolutionResult(
                entity=None,
                needs_review=True,
                reason="The observed name is already assigned to another active entity",
                candidates=candidates,
                confidence=decision.confidence,
            )
        alias_learned = not _has_exact_label(extracted.name, matched)
        return EntityResolutionResult(entity=matched, reason=decision.reason, alias_learned=alias_learned, candidates=candidates, confidence=decision.confidence)

    def _build_prompt(
        self,
        extracted: ExtractedEntity,
        namespace: str,
        document_context: str,
        candidates: list[EntityResolutionCandidate],
    ) -> str:
        payload = {
            "namespace": namespace,
            "observed_entity": extracted.model_dump(mode="json"),
            "document_context": document_context[:12000],
            "allowed_candidates": [candidate.model_dump(mode="json") for candidate in candidates],
            "automatic_match_threshold": self._auto_match_threshold,
        }
        return "\n\n".join(
            [
                get_entity_resolution_prompt(),
                "Entity-resolution context:",
                json.dumps(payload, indent=2, sort_keys=True),
            ]
        )


def _compatible_types(entity_type: str) -> set[str]:
    for group in _COMPATIBLE_TYPE_GROUPS:
        if entity_type in group:
            return set(group)
    return {entity_type}


def _rank_candidates(
    extracted: ExtractedEntity,
    entities: list[Entity],
    limit: int,
) -> list[EntityResolutionCandidate]:
    ranked: list[EntityResolutionCandidate] = []
    for entity in entities:
        labels = [entity.canonical_name, *entity.aliases]
        score = max(_name_similarity(name, label) for name in [extracted.name, *extracted.aliases] for label in labels)
        if score < 0.55:
            continue
        ranked.append(
            EntityResolutionCandidate(
                entity_id=entity.id,
                canonical_name=entity.canonical_name,
                entity_type=entity.entity_type,
                aliases=entity.aliases,
                description=entity.description,
                lexical_score=score,
            )
        )
    ranked.sort(key=lambda candidate: (-candidate.lexical_score, candidate.entity_id))
    return ranked[:limit]


def _has_exact_label(observed_name: str, entity: Entity) -> bool:
    observed = observed_name.casefold().strip()
    return observed == entity.canonical_name.casefold().strip() or any(
        observed == alias.casefold().strip() for alias in entity.aliases
    )


def _name_similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    left_core = [token for token in left_tokens if token not in _GENERIC_TYPE_WORDS] or left_tokens
    right_core = [token for token in right_tokens if token not in _GENERIC_TYPE_WORDS] or right_tokens
    left_compact = "".join(left_core)
    right_compact = "".join(right_core)

    if not left_compact or not right_compact:
        return 0.0
    if left_compact == right_compact:
        return 0.99
    if min(len(left_compact), len(right_compact)) >= 4 and (
        left_compact in right_compact or right_compact in left_compact
    ):
        return 0.9
    left_acronym = _acronym(left_tokens)
    right_acronym = _acronym(right_tokens)
    if (len(left_compact) >= 2 and left_compact == right_acronym) or (
        len(right_compact) >= 2 and right_compact == left_acronym
    ):
        return 0.9

    sequence_score = SequenceMatcher(None, left_compact, right_compact).ratio()
    left_set = set(left_core)
    right_set = set(right_core)
    union = left_set | right_set
    token_score = len(left_set & right_set) / len(union) if union else 0.0
    return max(sequence_score, token_score)


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.casefold())


def _acronym(tokens: list[str]) -> str:
    meaningful = [token for token in tokens if token not in _GENERIC_TYPE_WORDS]
    if len(meaningful) < 2:
        return ""
    return "".join(token[0] for token in meaningful if token)
