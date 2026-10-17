import asyncio

from app.ai.entity_resolution_models import EntityResolutionAction, EntityResolutionDecision
from app.ai.knowledge_extractor import KnowledgeExtractor
from app.ai.local_rules_client import LocalRulesClient
from app.documents.models import SourceChunk


def extract(content: str):
    chunk = SourceChunk(
        id="chunk-1", version_id="version-1", sequence=1,
        content=content, content_hash="test-hash",
    )
    return asyncio.run(KnowledgeExtractor(LocalRulesClient()).extract(chunk, "team"))


def test_explicit_sentences_and_pipe_rows_become_grounded_claims() -> None:
    result = extract(
        "The Billing Service calls the Inventory API.\n"
        "| Billing Service | DEPENDS_ON | Orders Database |\n"
        "Billing Service calls Inventory API.\n"
    )

    assert {(entity.name, entity.entity_type) for entity in result.entities} == {
        ("Billing Service", "SERVICE"),
        ("Inventory API", "API"),
        ("Orders Database", "DATABASE"),
    }
    assert [(claim.predicate, claim.evidence_text) for claim in result.claims] == [
        ("CALLS", "The Billing Service calls the Inventory API."),
        ("DEPENDS_ON", "| Billing Service | DEPENDS_ON | Orders Database |"),
    ]
    assert all(claim.object_entity is not None for claim in result.claims)


def test_free_form_and_negated_text_do_not_create_claims() -> None:
    result = extract(
        "Billing Service does not call Inventory API.\n"
        "This document discusses Inventory API and Billing Service.\n"
        "| Subject | Predicate | Object |\n"
    )
    assert result.entities == []
    assert result.claims == []


def test_uncertain_identity_is_sent_for_human_review() -> None:
    decision = asyncio.run(LocalRulesClient().generate_structured("candidate context", EntityResolutionDecision))
    assert decision.action == EntityResolutionAction.NEEDS_REVIEW
    assert decision.matched_entity_id is None
