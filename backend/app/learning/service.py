import re

from app.ai.entity_resolver import _compatible_types
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.evidence import Evidence
from app.domain.identifiers import stable_claim_id, stable_entity_id, stable_evidence_id
from app.learning.models import LearningBatch, ResolveIdentityRequest, ResolveIdentityResponse
from app.repositories.claim_repository import ClaimRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.learning_repository import LearningRepository
from app.repositories.gap_repository import GapRepository


class LearningService:
    def __init__(self, repository: LearningRepository, entities: EntityRepository, claims: ClaimRepository, documents: DocumentRepository) -> None:
        self.repository = repository
        self.entities = entities
        self.claims = claims
        self.documents = documents

    async def resolve(self, mention_id: str, namespace: str, request: ResolveIdentityRequest) -> ResolveIdentityResponse:
        mention = await self.repository.get_mention(mention_id)
        if mention is None or mention.namespace != namespace:
            raise ValueError("Clarification not found")
        batch = await self.repository.get_batch(mention.batch_id)
        if batch is None:
            raise ValueError("Learning batch not found")
        if batch.document_id is not None:
            current = await self.documents.get_current_version(batch.document_id)
            if current is None or current.id != batch.version_id or current.processing_status != "COMPLETE":
                raise ValueError("This source version is not current or has not finished processing")
        if request.decision == "MATCH":
            if not request.entity_id:
                raise ValueError("Select an existing entity")
            entity = await self.entities.get(request.entity_id)
            if entity is None or entity.namespace != namespace or entity.status != "ACTIVE":
                raise ValueError("Selected entity is not active in this team namespace")
            if entity.entity_type not in _compatible_types(mention.observed.entity_type):
                raise ValueError("Selected entity has an incompatible type")
        else:
            name = request.canonical_name or mention.observed.name
            entity = await self.entities.create(Entity(
                id=stable_entity_id(namespace, mention.observed.entity_type, name),
                entity_type=mention.observed.entity_type, canonical_name=name,
                namespace=namespace, description=mention.observed.description,
            ))
            if entity.namespace != namespace or entity.entity_type != mention.observed.entity_type or entity.canonical_name.casefold() != name.casefold() or entity.status != "ACTIVE":
                raise ValueError("Canonical name collides with another or retired entity; choose a distinct canonical name")
        # Identity, alias reservation, human reason, and bindings commit together.
        batch = await self.repository.resolve_mention(mention_id, namespace, entity.id, request.reason)
        applied = await self.apply_batch(batch, is_current=batch.document_id is None)
        if batch.document_id is not None:
            await self.documents.activate_version_evidence(batch.document_id, batch.version_id)
        unresolved = sum(entity.temporary_id not in batch.bindings for entity in batch.knowledge.entities)
        if batch.gap_id and unresolved == 0:
            await GapRepository(self.repository._client).resolve(batch.gap_id)
        await self.repository.mark_materialized(batch.id, batch.revision)
        return ResolveIdentityResponse(mention_id=mention_id, entity_id=entity.id, claims_applied=applied, pending_mentions=unresolved)

    async def apply_batch(self, batch: LearningBatch, is_current: bool) -> int:
        applied = 0
        for proposal in batch.knowledge.claims:
            references = [proposal.subject, proposal.object_entity, proposal.scope_entity]
            if any(reference is not None and reference not in batch.bindings for reference in references):
                continue
            evidence_text = re.sub(r"\s+", " ", proposal.evidence_text).strip()
            if not evidence_text or evidence_text not in re.sub(r"\s+", " ", batch.content).strip():
                continue
            subject_id = batch.bindings[proposal.subject]
            object_id = batch.bindings[proposal.object_entity] if proposal.object_entity else None
            scope_id = batch.bindings[proposal.scope_entity] if proposal.scope_entity else None
            for entity_id in [subject_id, object_id, scope_id]:
                if entity_id is None:
                    continue
                entity = await self.entities.get(entity_id)
                if entity is None or entity.namespace != batch.namespace or entity.status != "ACTIVE":
                    raise ValueError("Deferred claim references an unavailable team entity")
            existing = await self.claims.find_equivalent_active(subject_id, proposal.predicate, object_id, proposal.object_value, scope_id)
            claim_id = stable_claim_id(subject_id, proposal.predicate, object_id, proposal.object_value, scope_id)
            if existing is not None:
                claim_id = existing.id
                if batch.claim_status == "CONFIRMED" and existing.status != "CONFIRMED":
                    await self.claims.confirm(claim_id)
            else:
                await self.claims.create(Claim(
                    id=claim_id, subject_entity_id=subject_id, predicate=proposal.predicate,
                    object_entity_id=object_id, object_value=proposal.object_value,
                    scope_entity_id=scope_id, confidence=proposal.confidence, status=batch.claim_status,
                ))
            await self.claims.add_evidence(Evidence(
                id=stable_evidence_id(claim_id, batch.chunk_id or batch.id, proposal.evidence_text),
                claim_id=claim_id, source_id=batch.source_id, source_chunk_id=batch.chunk_id,
                excerpt=proposal.evidence_text, locator=batch.locator, is_current=is_current,
            ))
            applied += 1
        return applied
