"""Conservative, offline extraction for explicit document relationships.

This adapter intentionally understands a small grammar. It never guesses a
relationship from free-form prose, and uncertain identity matches are sent to
the existing human clarification workflow.
"""

import re
from typing import TypeVar

from pydantic import BaseModel

from app.ai.client import AIProviderError
from app.ai.entity_resolution_models import EntityResolutionDecision
from app.ai.extraction_models import ExtractedClaim, ExtractedEntity, ExtractedKnowledge
from app.domain.ontology import get_allowed_predicates


T = TypeVar("T", bound=BaseModel)

_BEGIN = "---BEGIN DOCUMENT CONTENT---\n"
_END = "\n---END DOCUMENT CONTENT---"
_VERBS = {
    "is part of": "PART_OF",
    "provides to": "PROVIDES_TO",
    "receives from": "RECEIVES_FROM",
    "publishes to": "PUBLISHES_TO",
    "reads from": "READS_FROM",
    "writes to": "WRITES_TO",
    "depends on": "DEPENDS_ON",
    "maps to": "MAPS_TO",
    "transforms to": "TRANSFORMS_TO",
    "owns": "OWNS",
    "calls": "CALLS",
    "exposes": "EXPOSES",
    "consumes": "CONSUMES",
    "produces": "PRODUCES",
    "represents": "REPRESENTS",
    "uses": "USES",
    "replaces": "REPLACES",
}
_VERB_PATTERN = re.compile(
    rf"^(?P<subject>.+?)\s+(?P<verb>{'|'.join(re.escape(verb) for verb in _VERBS)})\s+(?P<object>.+?)$",
    re.IGNORECASE,
)
_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./'-]*(?:\s+[A-Za-z0-9][A-Za-z0-9_./'-]*)*")
_TYPE_SUFFIXES = (
    ("external system", "EXTERNAL_SYSTEM"),
    ("business concept", "BUSINESS_CONCEPT"),
    ("team", "TEAM"),
    ("service", "SERVICE"),
    ("api", "API"),
    ("scheduler", "SCHEDULER"),
    ("database", "DATABASE"),
    ("table", "TABLE"),
    ("column", "COLUMN"),
    ("topic", "TOPIC"),
    ("flow", "FLOW"),
    ("system", "SYSTEM"),
    ("document", "DOCUMENT"),
    ("domain", "DOMAIN"),
)
_PRONOUNS = {"i", "it", "they", "them", "this", "that", "we", "you", "he", "she"}
_LOWERCASE_NAME_WORDS = {"and", "for", "of", "the", "to"}


class LocalRulesClient:
    async def generate_structured(self, prompt: str, response_model: type[T]) -> T:
        if response_model is ExtractedKnowledge:
            if _BEGIN not in prompt or _END not in prompt:
                raise AIProviderError("Local extraction did not receive document content")
            content = prompt.split(_BEGIN, 1)[1].rsplit(_END, 1)[0]
            return response_model.model_validate(_extract(content).model_dump())
        if response_model is EntityResolutionDecision:
            return response_model.model_validate({
                "action": "NEEDS_REVIEW",
                "confidence": 0.0,
                "reason": "Local extraction cannot safely choose between similar entities; confirm the identity in Questions for the team.",
            })
        raise AIProviderError("Local rules support document extraction only")


def _extract(content: str) -> ExtractedKnowledge:
    entities: dict[tuple[str, str], ExtractedEntity] = {}
    claims: list[ExtractedClaim] = []
    seen_claims: set[tuple[str, str, str]] = set()
    allowed_predicates = get_allowed_predicates()

    for line in content.splitlines():
        evidence = line.strip()
        if not evidence:
            continue
        parsed = _parse_pipe_row(evidence, allowed_predicates)
        statements = [(parsed, evidence, 0.9)] if parsed else [
            (_parse_sentence(sentence), sentence, 0.8)
            for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"^\s*(?:[-*]\s+|\d+[.)]\s+)", "", evidence))
        ]
        for statement, excerpt, confidence in statements:
            if statement is None:
                continue
            subject_name, predicate, object_name = statement
            subject_type = _infer_type(subject_name)
            object_type = _infer_type(object_name)
            subject_key = (subject_name.casefold(), subject_type)
            object_key = (object_name.casefold(), object_type)
            for key, name, entity_type in (
                (subject_key, subject_name, subject_type),
                (object_key, object_name, object_type),
            ):
                if key not in entities:
                    entities[key] = ExtractedEntity(
                        temporary_id=f"e{len(entities) + 1}", entity_type=entity_type, name=name
                    )
            claim_key = (subject_key[0], predicate, object_key[0])
            if claim_key in seen_claims:
                continue
            seen_claims.add(claim_key)
            claims.append(ExtractedClaim(
                subject=entities[subject_key].temporary_id,
                predicate=predicate,
                object_entity=entities[object_key].temporary_id,
                confidence=confidence,
                evidence_text=excerpt,
            ))
    return ExtractedKnowledge(entities=list(entities.values()), claims=claims)


def _parse_pipe_row(line: str, allowed_predicates: set[str]) -> tuple[str, str, str] | None:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) != 3:
        return None
    predicate = cells[1].upper().replace(" ", "_")
    subject, object_name = _clean_name(cells[0]), _clean_name(cells[2])
    if predicate not in allowed_predicates - {"PURPOSE"} or not _valid_name(subject) or not _valid_name(object_name):
        return None
    return subject, predicate, object_name


def _parse_sentence(sentence: str) -> tuple[str, str, str] | None:
    match = _VERB_PATTERN.fullmatch(sentence.strip().rstrip(".!?"))
    if match is None:
        return None
    subject = _clean_name(match["subject"])
    object_name = _clean_name(match["object"])
    if not _valid_name(subject) or not _valid_name(object_name):
        return None
    return subject, _VERBS[match["verb"].casefold()], object_name


def _clean_name(value: str) -> str:
    value = value.strip().strip("*` ")
    value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.IGNORECASE)
    return value.strip().strip("*` ")


def _valid_name(value: str) -> bool:
    return (
        1 <= len(value) <= 100
        and len(value.split()) <= 8
        and value.casefold() not in _PRONOUNS
        and any(character.isupper() for character in value)
        and all(word[0].isupper() or word[0].isdigit() or word.casefold() in _LOWERCASE_NAME_WORDS for word in value.split())
        and _NAME_PATTERN.fullmatch(value) is not None
    )


def _infer_type(name: str) -> str:
    folded = name.casefold()
    for suffix, entity_type in _TYPE_SUFFIXES:
        if folded.endswith(" " + suffix) or folded == suffix:
            return entity_type
    return "BUSINESS_CONCEPT"
