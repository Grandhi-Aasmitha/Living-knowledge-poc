from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.enums import ClaimStatus, GapPriority, SourceType
from app.domain.evidence import Evidence
from app.domain.gap import KnowledgeGap
from app.domain.source import KnowledgeSource


def test_valid_entity_type_accepted() -> None:
    entity = Entity(
        id="test:entity:service",
        entity_type="SERVICE",
        canonical_name="Test Service",
        namespace="test",
    )

    assert entity.entity_type == "SERVICE"


def test_invalid_entity_type_rejected() -> None:
    with pytest.raises(ValidationError):
        Entity(
            id="test:entity:unknown",
            entity_type="UNKNOWN",
            canonical_name="Unknown",
            namespace="test",
        )


def test_entity_rejects_blank_required_strings() -> None:
    with pytest.raises(ValidationError):
        Entity(id=" ", entity_type="SERVICE", canonical_name="Test Service", namespace="test")

    with pytest.raises(ValidationError):
        Entity(id="test:entity:service", entity_type="SERVICE", canonical_name=" ", namespace="test")

    with pytest.raises(ValidationError):
        Entity(id="test:entity:service", entity_type="SERVICE", canonical_name="Test Service", namespace=" ")


def test_entity_trims_valid_strings() -> None:
    entity = Entity(id=" test:entity:service ", entity_type=" SERVICE ", canonical_name=" Test Service ", namespace=" test ")

    assert entity.id == "test:entity:service"
    assert entity.entity_type == "SERVICE"
    assert entity.canonical_name == "Test Service"
    assert entity.namespace == "test"


def test_valid_claim_predicate_accepted() -> None:
    claim = Claim(
        subject_entity_id="test:entity:subject",
        predicate="OWNS",
        object_entity_id="test:entity:object",
        status=ClaimStatus.CONFIRMED,
    )

    assert claim.predicate == "OWNS"


def test_invalid_predicate_rejected() -> None:
    with pytest.raises(ValidationError):
        Claim(
            subject_entity_id="test:entity:subject",
            predicate="UNKNOWN",
            object_entity_id="test:entity:object",
            status=ClaimStatus.CONFIRMED,
        )


def test_claim_rejects_blank_required_and_optional_strings() -> None:
    with pytest.raises(ValidationError):
        Claim(subject_entity_id=" ", predicate="OWNS", object_entity_id="test:entity:object", status=ClaimStatus.CONFIRMED)

    with pytest.raises(ValidationError):
        Claim(subject_entity_id="test:entity:subject", predicate="OWNS", object_entity_id=" ", status=ClaimStatus.CONFIRMED)

    with pytest.raises(ValidationError):
        Claim(subject_entity_id="test:entity:subject", predicate="PURPOSE", object_value=" ", status=ClaimStatus.CONFIRMED)


def test_claim_with_entity_object_accepted() -> None:
    claim = Claim(
        subject_entity_id="test:entity:subject",
        predicate="DEPENDS_ON",
        object_entity_id="test:entity:object",
        status=ClaimStatus.PROPOSED,
    )

    assert claim.object_entity_id == "test:entity:object"
    assert claim.object_value is None


def test_claim_with_literal_object_accepted() -> None:
    claim = Claim(
        subject_entity_id="test:entity:subject",
        predicate="PURPOSE",
        object_value="Coordinates test flow",
        status=ClaimStatus.PROPOSED,
    )

    assert claim.object_value == "Coordinates test flow"
    assert claim.object_entity_id is None


def test_claim_with_both_object_types_rejected() -> None:
    with pytest.raises(ValidationError):
        Claim(
            subject_entity_id="test:entity:subject",
            predicate="PURPOSE",
            object_entity_id="test:entity:object",
            object_value="Coordinates test flow",
            status=ClaimStatus.PROPOSED,
        )


def test_claim_with_neither_object_rejected() -> None:
    with pytest.raises(ValidationError):
        Claim(
            subject_entity_id="test:entity:subject",
            predicate="PURPOSE",
            status=ClaimStatus.PROPOSED,
        )


def test_confidence_below_zero_rejected() -> None:
    with pytest.raises(ValidationError):
        Claim(
            subject_entity_id="test:entity:subject",
            predicate="PURPOSE",
            object_value="Coordinates test flow",
            confidence=-0.1,
            status=ClaimStatus.PROPOSED,
        )


def test_confidence_above_one_rejected() -> None:
    with pytest.raises(ValidationError):
        Claim(
            subject_entity_id="test:entity:subject",
            predicate="PURPOSE",
            object_value="Coordinates test flow",
            confidence=1.1,
            status=ClaimStatus.PROPOSED,
        )


def test_valid_temporal_range_accepted() -> None:
    valid_from = datetime.now(UTC)
    valid_to = valid_from + timedelta(days=1)

    claim = Claim(
        subject_entity_id="test:entity:subject",
        predicate="PURPOSE",
        object_value="Coordinates test flow",
        status=ClaimStatus.CONFIRMED,
        valid_from=valid_from,
        valid_to=valid_to,
    )

    assert claim.valid_to == valid_to


def test_invalid_temporal_range_rejected() -> None:
    valid_from = datetime.now(UTC)
    valid_to = valid_from - timedelta(days=1)

    with pytest.raises(ValidationError):
        Claim(
            subject_entity_id="test:entity:subject",
            predicate="PURPOSE",
            object_value="Coordinates test flow",
            status=ClaimStatus.CONFIRMED,
            valid_from=valid_from,
            valid_to=valid_to,
        )


def test_evidence_rejects_blank_identifiers() -> None:
    with pytest.raises(ValidationError):
        Evidence(id=" ", claim_id="test:claim", source_id="test:source")

    with pytest.raises(ValidationError):
        Evidence(claim_id="test:claim", source_id=" ")


def test_gap_rejects_blank_core_fields() -> None:
    with pytest.raises(ValidationError):
        KnowledgeGap(entity_id=" ", gap_type="MISSING_OWNER", description="Owner missing", priority=GapPriority.HIGH)

    with pytest.raises(ValidationError):
        KnowledgeGap(entity_id="test:entity", gap_type="MISSING_OWNER", description=" ", priority=GapPriority.HIGH)


def test_source_rejects_blank_title() -> None:
    with pytest.raises(ValidationError):
        KnowledgeSource(source_type=SourceType.SYSTEM, title=" ")
