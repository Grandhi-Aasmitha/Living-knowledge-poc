from datetime import UTC, datetime

from app.domain.entity import Entity
from app.entity_merges import find_candidates, merged_batch_payload, merged_mention_payload
from app.learning.models import EntityMention, LearningBatch
from app.ai.extraction_models import ExtractedEntity, ExtractedKnowledge


def test_duplicate_suggestions_are_same_type_only() -> None:
    entities = [
        Entity(id="1", namespace="test", canonical_name="Aster Tracking Service", entity_type="SERVICE"),
        Entity(id="2", namespace="test", canonical_name="Aster Track Service", entity_type="SERVICE"),
        Entity(id="3", namespace="test", canonical_name="Aster Tracking Team", entity_type="TEAM"),
    ]
    suggestions = find_candidates(entities, threshold=0.5)
    assert [(candidate.first.id, candidate.second.id) for candidate in suggestions] == [("1", "2")]


def test_saved_learning_references_follow_approved_merge() -> None:
    observed = ExtractedEntity(temporary_id="service", name="Aster Tracking", entity_type="SERVICE")
    mention = EntityMention(id="mention", batch_id="batch", namespace="test", observed=observed,
                            status="RESOLVED", entity_id="duplicate", created_at=datetime.now(UTC))
    batch = LearningBatch(id="batch", namespace="test", source_id="source", content="sample",
                          knowledge=ExtractedKnowledge(entities=[observed], claims=[]), bindings={"service": "duplicate"})
    assert EntityMention.model_validate_json(merged_mention_payload(mention.model_dump_json(), "duplicate", "keep")).entity_id == "keep"
    assert LearningBatch.model_validate_json(merged_batch_payload(batch.model_dump_json(), "duplicate", "keep")).bindings == {"service": "keep"}
