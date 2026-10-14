import asyncio
from typing import TypeVar

import pytest
from pydantic import BaseModel

from app.ai.client import AIProviderError
from app.ai.entity_resolution_models import EntityResolutionDecision
from app.ai.entity_resolver import EntityResolver
from app.ai.extraction_models import ExtractedEntity
from app.domain.entity import Entity


T = TypeVar("T", bound=BaseModel)


def run(coro):
    return asyncio.run(coro)


class FakeAIClient:
    def __init__(self, decision: dict | None = None) -> None:
        self.decision = decision
        self.calls = 0
        self.prompt = ""

    async def generate_structured(self, prompt: str, response_model: type[T]) -> T:
        self.calls += 1
        self.prompt = prompt
        if self.decision is None:
            raise AssertionError("Unexpected entity-resolution AI call")
        assert response_model is EntityResolutionDecision
        return response_model(**self.decision)


class FakeEntityRepository:
    def __init__(self, entities: list[Entity]) -> None:
        self.entities = {entity.id: entity for entity in entities}
        self.added_aliases: list[tuple[str, str]] = []

    async def find_by_name_or_alias(self, name: str, namespace: str) -> Entity | None:
        folded = name.casefold()
        for entity in self.entities.values():
            if entity.namespace != namespace:
                continue
            if entity.canonical_name.casefold() == folded or any(alias.casefold() == folded for alias in entity.aliases):
                return entity
        return None

    async def list_active_for_resolution(self, namespace: str, entity_types: list[str]) -> list[Entity]:
        return [
            entity
            for entity in self.entities.values()
            if entity.namespace == namespace and entity.entity_type in entity_types and entity.status == "ACTIVE"
        ]

    async def get(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)

    async def add_alias(self, entity_id: str, alias: str) -> Entity:
        entity = self.entities[entity_id]
        if alias.casefold() not in {item.casefold() for item in entity.aliases}:
            entity = entity.model_copy(update={"aliases": [*entity.aliases, alias]})
            self.entities[entity_id] = entity
            self.added_aliases.append((entity_id, alias))
        return entity


def tstvs_system() -> Entity:
    return Entity(
        id="tstvs:system:tstvs-system",
        entity_type="SYSTEM",
        canonical_name="TSTVS System",
        description="Tactical scheduling and validation application",
        namespace="tstvs",
    )


def test_ai_matches_contextual_name_without_writing_before_provenance_is_saved() -> None:
    repository = FakeEntityRepository([tstvs_system()])
    ai = FakeAIClient(
        {
            "action": "MATCH",
            "matched_entity_id": "tstvs:system:tstvs-system",
            "confidence": 0.97,
            "reason": "The acronym and application context identify the existing system.",
        }
    )
    resolver = EntityResolver(ai, repository)

    result = run(
        resolver.resolve(
            ExtractedEntity(temporary_id="system", entity_type="SYSTEM", name="TSTVS"),
            namespace="tstvs",
            document_context="TSTVS publishes scheduled dispatch events.",
        )
    )

    assert result.entity is not None
    assert result.entity.id == "tstvs:system:tstvs-system"
    assert result.created is False
    assert result.alias_learned is True
    assert repository.added_aliases == []
    assert "TSTVS publishes scheduled dispatch events." in ai.prompt
    assert '"entity_id": "tstvs:system:tstvs-system"' in ai.prompt


def test_low_confidence_match_is_deferred_for_review() -> None:
    repository = FakeEntityRepository([tstvs_system()])
    ai = FakeAIClient(
        {
            "action": "MATCH",
            "matched_entity_id": "tstvs:system:tstvs-system",
            "confidence": 0.7,
            "reason": "The name is similar but the context is incomplete.",
        }
    )
    resolver = EntityResolver(ai, repository, auto_match_threshold=0.9)

    result = run(
        resolver.resolve(
            ExtractedEntity(temporary_id="system", entity_type="SYSTEM", name="TSTVS"),
            namespace="tstvs",
            document_context="TSTVS is referenced here.",
        )
    )

    assert result.entity is None
    assert result.needs_review is True
    assert result.alias_learned is False
    assert repository.added_aliases == []


def test_team_and_similarly_named_system_are_not_resolution_candidates() -> None:
    repository = FakeEntityRepository([tstvs_system()])
    ai = FakeAIClient()
    resolver = EntityResolver(ai, repository)

    result = run(
        resolver.resolve(
            ExtractedEntity(temporary_id="team", entity_type="TEAM", name="TSTVS"),
            namespace="tstvs",
            document_context="The TSTVS team owns the application.",
        )
    )

    assert result.created is True
    assert result.entity is None
    assert ai.calls == 0


def test_unknown_candidate_id_is_rejected() -> None:
    repository = FakeEntityRepository([tstvs_system()])
    ai = FakeAIClient(
        {
            "action": "MATCH",
            "matched_entity_id": "invented-id",
            "confidence": 1.0,
            "reason": "Invalid provider response",
        }
    )
    resolver = EntityResolver(ai, repository)

    with pytest.raises(AIProviderError, match="unknown candidate"):
        run(
            resolver.resolve(
                ExtractedEntity(temporary_id="system", entity_type="SYSTEM", name="TSTVS"),
                namespace="tstvs",
                document_context="TSTVS publishes events.",
            )
        )


def test_existing_duplicate_label_is_not_silently_reassigned() -> None:
    short_name = Entity(
        id="tstvs:system:tstvs",
        entity_type="SYSTEM",
        canonical_name="TSTVS",
        namespace="tstvs",
    )
    repository = FakeEntityRepository([short_name, tstvs_system()])
    ai = FakeAIClient(
        {
            "action": "MATCH",
            "matched_entity_id": "tstvs:system:tstvs-system",
            "confidence": 0.98,
            "reason": "The richer system description is the intended canonical entity.",
        }
    )
    resolver = EntityResolver(ai, repository)

    result = run(
        resolver.resolve(
            ExtractedEntity(temporary_id="system", entity_type="SYSTEM", name="TSTVS"),
            namespace="tstvs",
            document_context="TSTVS publishes scheduled dispatch events.",
        )
    )

    assert result.entity is None
    assert result.needs_review is True
    assert repository.added_aliases == []


def test_extracted_aliases_participate_in_candidate_generation() -> None:
    repository = FakeEntityRepository([tstvs_system()])
    ai = FakeAIClient({"action": "MATCH", "matched_entity_id": tstvs_system().id, "confidence": 0.97, "reason": "Document explicitly provides the alternate name"})
    result = run(EntityResolver(ai, repository).resolve(
        ExtractedEntity(temporary_id="system", entity_type="SYSTEM", name="Aurora", aliases=["TSTVS System"]),
        "tstvs", "Aurora is another name for TSTVS System.",
    ))
    assert result.entity.id == tstvs_system().id
    assert ai.calls == 1


def test_low_confidence_create_is_reviewed_instead_of_spawning_a_duplicate() -> None:
    repository = FakeEntityRepository([tstvs_system()])
    ai = FakeAIClient({"action": "CREATE", "confidence": 0.5, "reason": "Unsure whether these names are distinct"})
    result = run(EntityResolver(ai, repository).resolve(ExtractedEntity(temporary_id="system", entity_type="SYSTEM", name="Tactical STVS"), "tstvs", "Tactical STVS is mentioned."))
    assert result.needs_review
    assert not result.created
