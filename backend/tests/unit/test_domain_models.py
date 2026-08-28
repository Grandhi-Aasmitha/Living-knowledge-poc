from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.enums import ClaimStatus


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
