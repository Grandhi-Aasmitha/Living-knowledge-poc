import pytest
from pydantic import ValidationError

from app.assistant.models import AnswerDraft, KnowledgeQueryPlan, QueryDirection


def test_valid_query_plan_accepts_controlled_predicates() -> None:
    plan = KnowledgeQueryPlan(entity_names=["Scheduler Service"], predicates=["OWNS"], direction=QueryDirection.INCOMING)

    assert plan.entity_names == ["Scheduler Service"]
    assert plan.predicates == ["OWNS"]


def test_query_plan_rejects_more_than_three_entities() -> None:
    with pytest.raises(ValidationError):
        KnowledgeQueryPlan(entity_names=["A", "B", "C", "D"])


def test_query_plan_rejects_more_than_ten_predicates() -> None:
    with pytest.raises(ValidationError):
        KnowledgeQueryPlan(entity_names=["A"], predicates=["OWNS"] * 11)


def test_query_plan_rejects_invalid_predicate() -> None:
    with pytest.raises(ValidationError):
        KnowledgeQueryPlan(entity_names=["A"], predicates=["MAKES_UP_FACTS"])


def test_query_plan_rejects_blank_entity_name() -> None:
    with pytest.raises(ValidationError):
        KnowledgeQueryPlan(entity_names=[""])


def test_query_plan_rejects_invalid_direction() -> None:
    with pytest.raises(ValidationError):
        KnowledgeQueryPlan(entity_names=["A"], direction="SIDEWAYS")


def test_query_plan_has_no_cypher_field() -> None:
    assert "cypher" not in KnowledgeQueryPlan.model_fields
    assert "query" not in KnowledgeQueryPlan.model_fields


def test_answer_draft_requires_citations_when_not_insufficient() -> None:
    with pytest.raises(ValidationError):
        AnswerDraft(answer="A owns B.", insufficient_knowledge=False)


def test_answer_draft_allows_no_citations_when_insufficient() -> None:
    draft = AnswerDraft(answer="I do not know.", insufficient_knowledge=True)

    assert draft.cited_claim_ids == []
    assert draft.cited_evidence_ids == []
