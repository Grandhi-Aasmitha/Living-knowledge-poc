from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.ai.entity_resolver import _name_similarity
from app.domain.entity import Entity
from app.learning.models import EntityMention, LearningBatch
from app.domain.validation import NonBlankString


class DuplicateCandidate(BaseModel):
    first: Entity
    second: Entity
    similarity: float


class MergeRequest(BaseModel):
    namespace: NonBlankString
    keep_id: NonBlankString
    duplicate_id: NonBlankString
    reviewer: NonBlankString = Field(max_length=120)
    reason: NonBlankString = Field(max_length=1000)


class MergeResult(BaseModel):
    kept: Entity
    retired_id: str
    claims_updated: int
    gaps_updated: int
    mentions_updated: int


def find_candidates(entities: list[Entity], threshold: float = 0.85) -> list[DuplicateCandidate]:
    candidates: list[DuplicateCandidate] = []
    for index, first in enumerate(entities):
        for second in entities[index + 1:]:
            if first.entity_type != second.entity_type:
                continue
            score = max(_name_similarity(left, right) for left in [first.canonical_name, *first.aliases] for right in [second.canonical_name, *second.aliases])
            if score >= threshold:
                candidates.append(DuplicateCandidate(first=first, second=second, similarity=round(score, 3)))
    return sorted(candidates, key=lambda item: (-item.similarity, item.first.id, item.second.id))[:100]


def merged_batch_payload(payload: str, duplicate_id: str, keep_id: str) -> str:
    batch = LearningBatch.model_validate_json(payload)
    batch.bindings = {key: keep_id if value == duplicate_id else value for key, value in batch.bindings.items()}
    return batch.model_dump_json()


def merged_mention_payload(payload: str, duplicate_id: str, keep_id: str) -> str:
    mention = EntityMention.model_validate_json(payload)
    if mention.entity_id == duplicate_id:
        mention.entity_id = keep_id
    for candidate in mention.candidates:
        if candidate.entity_id == duplicate_id:
            candidate.entity_id = keep_id
    return mention.model_dump_json()


def merge_timestamp() -> str:
    return datetime.now(UTC).isoformat()
