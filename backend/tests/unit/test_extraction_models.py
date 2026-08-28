import pytest
from pydantic import ValidationError

from app.ai.extraction_models import ExtractedClaim, ExtractedEntity, ExtractedKnowledge


def test_valid_entity_type_accepted() -> None:
    entity = ExtractedEntity(temporary_id="e1", entity_type="SERVICE", name="Ingestion Service")

    assert entity.entity_type == "SERVICE"


def test_invalid_entity_type_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractedEntity(temporary_id="e1", entity_type="UNKNOWN", name="Unknown")


def test_valid_predicate_accepted() -> None:
    claim = ExtractedClaim(
        subject="e1",
        predicate="PUBLISHES_TO",
        object_entity="e2",
        confidence=0.8,
        evidence_text="A publishes to B.",
    )

    assert claim.predicate == "PUBLISHES_TO"


def test_invalid_predicate_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractedClaim(
            subject="e1",
            predicate="UPSTREAM_OF",
            object_entity="e2",
            confidence=0.8,
            evidence_text="A is upstream of B.",
        )


def test_literal_object_claim_is_valid() -> None:
    claim = ExtractedClaim(
        subject="e1",
        predicate="PURPOSE",
        object_value="Publishes transformed prices.",
        confidence=0.9,
        evidence_text="The purpose is publishing transformed prices.",
    )

    assert claim.object_value == "Publishes transformed prices."


def test_both_object_types_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractedClaim(
            subject="e1",
            predicate="PURPOSE",
            object_entity="e2",
            object_value="Publishes transformed prices.",
            confidence=0.9,
            evidence_text="The purpose is publishing transformed prices.",
        )


def test_neither_object_type_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractedClaim(subject="e1", predicate="PURPOSE", confidence=0.9, evidence_text="Evidence")


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_bounds(confidence: float) -> None:
    with pytest.raises(ValidationError):
        ExtractedClaim(
            subject="e1",
            predicate="PUBLISHES_TO",
            object_entity="e2",
            confidence=confidence,
            evidence_text="Evidence",
        )


def test_unknown_temporary_entity_reference_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractedKnowledge(
            entities=[ExtractedEntity(temporary_id="e1", entity_type="SERVICE", name="Ingestion Service")],
            claims=[
                ExtractedClaim(
                    subject="e1",
                    predicate="PUBLISHES_TO",
                    object_entity="missing",
                    confidence=0.9,
                    evidence_text="The Ingestion Service publishes to the Transformed Price Topic.",
                )
            ],
        )


def test_valid_extracted_knowledge() -> None:
    knowledge = ExtractedKnowledge(
        entities=[
            ExtractedEntity(temporary_id="e1", entity_type="SERVICE", name="Ingestion Service"),
            ExtractedEntity(temporary_id="e2", entity_type="TOPIC", name="Transformed Price Topic"),
        ],
        claims=[
            ExtractedClaim(
                subject="e1",
                predicate="PUBLISHES_TO",
                object_entity="e2",
                confidence=0.9,
                evidence_text="The Ingestion Service publishes to the Transformed Price Topic.",
            )
        ],
    )

    assert len(knowledge.claims) == 1
