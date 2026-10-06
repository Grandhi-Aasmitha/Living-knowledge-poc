import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.ai.client import AIProviderError, StructuredAIClient
from app.ai.extraction_models import ExtractedClaim, ExtractedEntity, ExtractedKnowledge
from app.ai.knowledge_extractor import KnowledgeExtractor
from app.documents.chunker import DocumentChunker
from app.documents.models import SourceChunk, SourceDocument, SourceVersion
from app.documents.parsers import NoExtractableTextError, UnsupportedDocumentTypeError, get_parser, is_supported_filename
from app.documents.storage import DocumentStorage, safe_original_filename
from app.domain.claim import Claim
from app.domain.entity import Entity
from app.domain.enums import ClaimStatus, EntityStatus, SourceType
from app.domain.evidence import Evidence
from app.domain.identifiers import (
    normalize_filename,
    stable_claim_id,
    stable_entity_id,
    stable_evidence_id,
    stable_source_document_id,
    stable_source_version_id,
)
from app.domain.source import KnowledgeSource
from app.repositories.claim_repository import ClaimRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.source_repository import SourceRepository


FILE_UPLOAD_SOURCE_ID = "source:file-upload"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionResult:
    document_id: str
    version_id: str | None
    status: str
    chunks_processed: int
    entities_created: int
    entities_reused: int
    claims_created: int
    claims_reused: int
    evidence_created: int
    claims_rejected: int
    unresolved_terms: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _ResolvedClaim:
    claim: Claim
    evidence: Evidence


class FileIngestionService:
    def __init__(
        self,
        ai_client: StructuredAIClient,
        source_repository: SourceRepository,
        document_repository: DocumentRepository,
        entity_repository: EntityRepository,
        claim_repository: ClaimRepository,
        upload_directory: str,
        max_upload_size_mb: int,
        max_chunk_chars: int,
        max_chunks_per_document: int,
    ) -> None:
        self._storage = DocumentStorage(upload_directory, max_upload_size_mb)
        self._chunker = DocumentChunker(max_chunk_chars, max_chunks_per_document)
        self._extractor = KnowledgeExtractor(ai_client)
        self._source_repository = source_repository
        self._document_repository = document_repository
        self._entity_repository = entity_repository
        self._claim_repository = claim_repository

    async def ingest(self, content: bytes, original_filename: str, namespace: str = "tstvs") -> IngestionResult:
        filename = safe_original_filename(original_filename)
        if not is_supported_filename(filename):
            logger.info("Rejected unsupported upload extension=%s namespace=%s", _file_extension(filename), namespace)
            raise UnsupportedDocumentTypeError("Unsupported file type. Supported types: .pdf, .docx, .pptx, .txt, .md")
        self._storage.validate_size(content)
        content_hash = self._storage.content_hash(content)
        external_id = normalize_filename(filename)
        document_id = stable_source_document_id(filename)
        logger.info(
            "Starting file ingestion document_id=%s extension=%s namespace=%s bytes=%d content_hash_prefix=%s",
            document_id,
            _file_extension(filename),
            namespace,
            len(content),
            content_hash[:12],
        )
        existing = await self._document_repository.get_document_by_external_id(FILE_UPLOAD_SOURCE_ID, external_id)
        if existing is not None and existing.current_content_hash == content_hash:
            current_version = await self._document_repository.get_current_version(existing.id)
            logger.info(
                "File ingestion unchanged document_id=%s version_id=%s namespace=%s",
                existing.id,
                current_version.id if current_version is not None else None,
                namespace,
            )
            return IngestionResult(
                document_id=existing.id,
                version_id=current_version.id if current_version is not None else None,
                status="UNCHANGED",
                chunks_processed=0,
                entities_created=0,
                entities_reused=0,
                claims_created=0,
                claims_reused=0,
                evidence_created=0,
                claims_rejected=0,
                unresolved_terms=[],
            )

        storage_key, path = self._storage.save(content, filename, content_hash)
        parsed = get_parser(filename).parse(path, filename)
        draft_chunks = self._chunker.chunk(parsed)
        if not draft_chunks:
            logger.warning("File ingestion found no chunks document_id=%s extension=%s namespace=%s", document_id, _file_extension(filename), namespace)
            raise NoExtractableTextError("No extractable text found in the uploaded document.")

        next_version = 1 if existing is None else existing.latest_version + 1
        version_id = stable_source_version_id(document_id, content_hash)
        chunks = self._chunker.materialize(version_id, draft_chunks)
        logger.info(
            "File ingestion parsed document_id=%s version_id=%s extension=%s namespace=%s sections=%d chunks=%d next_version=%d",
            document_id,
            version_id,
            _file_extension(filename),
            namespace,
            len(parsed.sections),
            len(chunks),
            next_version,
        )
        extracted_by_chunk: list[tuple[SourceChunk, ExtractedKnowledge]] = []
        for chunk in chunks:
            try:
                extracted = await self._extractor.extract(chunk, namespace)
            except AIProviderError as error:
                logger.warning(
                    "File ingestion AI extraction failed document_id=%s version_id=%s namespace=%s chunk_sequence=%d chunk_count=%d provider_error=%s",
                    document_id,
                    version_id,
                    namespace,
                    chunk.sequence,
                    len(chunks),
                    str(error),
                )
                raise
            logger.info(
                "File ingestion extracted chunk document_id=%s version_id=%s namespace=%s chunk_sequence=%d entities=%d claims=%d unresolved_terms=%d",
                document_id,
                version_id,
                namespace,
                chunk.sequence,
                len(extracted.entities),
                len(extracted.claims),
                len(extracted.unresolved_terms),
            )
            extracted_by_chunk.append((chunk, extracted))

        now = datetime.now(UTC)
        source = await self._source_repository.create(
            KnowledgeSource(
                id=FILE_UPLOAD_SOURCE_ID,
                source_type=SourceType.FILE_UPLOAD,
                title="Uploaded Documents",
                created_at=now,
            )
        )
        document = existing or SourceDocument(
            id=document_id,
            source_id=source.id,
            external_id=external_id,
            title=parsed.title,
            filename=filename,
            latest_version=next_version,
            current_content_hash=content_hash,
            created_at=now,
            updated_at=now,
        )
        await self._document_repository.create_document(document)
        version = await self._document_repository.create_version(
            SourceVersion(
                id=version_id,
                document_id=document.id,
                version_number=next_version,
                content_hash=content_hash,
                storage_key=storage_key,
                created_at=now,
            )
        )
        await self._document_repository.create_chunks(chunks)

        entity_by_temp_id: dict[str, Entity] = {}
        seen_entity_ids: set[str] = set()
        created_entity_ids: set[str] = set()
        reused_entity_ids: set[str] = set()
        unresolved_terms: list[str] = []
        for _, knowledge in extracted_by_chunk:
            unresolved_terms.extend(knowledge.unresolved_terms)
            for extracted_entity in knowledge.entities:
                expected_id = stable_entity_id(namespace, extracted_entity.entity_type, extracted_entity.name)
                existed = await self._entity_repository.find_by_name_or_alias(extracted_entity.name, namespace)
                entity = await self._resolve_entity(extracted_entity, namespace, now, existed)
                entity_by_temp_id[extracted_entity.temporary_id] = entity
                if entity.id in seen_entity_ids:
                    continue
                seen_entity_ids.add(entity.id)
                if existed is None and entity.id == expected_id:
                    created_entity_ids.add(entity.id)
                else:
                    reused_entity_ids.add(entity.id)

        claims_created = 0
        claims_reused = 0
        evidence_created = 0
        claims_rejected = 0
        for chunk, knowledge in extracted_by_chunk:
            for extracted_claim in knowledge.claims:
                if not _evidence_is_supported(extracted_claim.evidence_text, chunk.content):
                    claims_rejected += 1
                    logger.warning(
                        "File ingestion rejected unsupported evidence document_id=%s version_id=%s namespace=%s chunk_sequence=%d rejected_count=%d",
                        document.id,
                        version.id,
                        namespace,
                        chunk.sequence,
                        claims_rejected,
                    )
                    continue
                resolved = self._build_claim(extracted_claim, entity_by_temp_id, chunk, source.id, now)
                existing_claim = await self._claim_repository.find_equivalent_active(
                    subject_entity_id=resolved.claim.subject_entity_id,
                    predicate=resolved.claim.predicate,
                    object_entity_id=resolved.claim.object_entity_id,
                    object_value=resolved.claim.object_value,
                    scope_entity_id=resolved.claim.scope_entity_id,
                )
                if existing_claim is None:
                    await self._claim_repository.create(resolved.claim)
                    claim_id = resolved.claim.id
                    claims_created += 1
                else:
                    claim_id = existing_claim.id
                    claims_reused += 1
                await self._claim_repository.add_evidence(resolved.evidence.model_copy(update={"claim_id": claim_id}))
                evidence_created += 1

        await self._document_repository.mark_document_current(document.id, next_version, content_hash, now)
        result = IngestionResult(
            document_id=document.id,
            version_id=version.id,
            status="INGESTED",
            chunks_processed=len(chunks),
            entities_created=len(created_entity_ids),
            entities_reused=len(reused_entity_ids - created_entity_ids),
            claims_created=claims_created,
            claims_reused=claims_reused,
            evidence_created=evidence_created,
            claims_rejected=claims_rejected,
            unresolved_terms=sorted(set(unresolved_terms)),
        )
        logger.info(
            "File ingestion completed document_id=%s version_id=%s namespace=%s chunks=%d entities_created=%d entities_reused=%d claims_created=%d claims_reused=%d evidence_created=%d claims_rejected=%d unresolved_terms=%d",
            result.document_id,
            result.version_id,
            namespace,
            result.chunks_processed,
            result.entities_created,
            result.entities_reused,
            result.claims_created,
            result.claims_reused,
            result.evidence_created,
            result.claims_rejected,
            len(result.unresolved_terms),
        )
        return result

    async def _resolve_entity(
        self,
        extracted: ExtractedEntity,
        namespace: str,
        now: datetime,
        existing: Entity | None,
    ) -> Entity:
        if existing is not None:
            return existing
        return await self._entity_repository.create(
            Entity(
                id=stable_entity_id(namespace, extracted.entity_type, extracted.name),
                entity_type=extracted.entity_type,
                canonical_name=extracted.name,
                description=extracted.description,
                namespace=namespace,
                status=EntityStatus.ACTIVE,
                aliases=extracted.aliases,
                created_at=now,
                updated_at=now,
            )
        )

    def _build_claim(
        self,
        extracted: ExtractedClaim,
        entity_by_temp_id: dict[str, Entity],
        chunk: SourceChunk,
        source_id: str,
        now: datetime,
    ) -> _ResolvedClaim:
        subject = entity_by_temp_id[extracted.subject]
        object_entity = entity_by_temp_id[extracted.object_entity] if extracted.object_entity is not None else None
        scope_entity = entity_by_temp_id[extracted.scope_entity] if extracted.scope_entity is not None else None
        claim_id = stable_claim_id(
            subject_entity_id=subject.id,
            predicate=extracted.predicate,
            object_entity_id=object_entity.id if object_entity is not None else None,
            object_value=extracted.object_value,
            scope_entity_id=scope_entity.id if scope_entity is not None else None,
        )
        claim = Claim(
            id=claim_id,
            subject_entity_id=subject.id,
            predicate=extracted.predicate,
            object_entity_id=object_entity.id if object_entity is not None else None,
            object_value=extracted.object_value,
            scope_entity_id=scope_entity.id if scope_entity is not None else None,
            confidence=extracted.confidence,
            status=ClaimStatus.PROPOSED,
            created_at=now,
            updated_at=now,
        )
        evidence = Evidence(
            id=stable_evidence_id(claim_id, chunk.id, extracted.evidence_text),
            claim_id=claim.id,
            source_id=source_id,
            source_chunk_id=chunk.id,
            excerpt=extracted.evidence_text,
            locator=chunk.locator,
            created_at=now,
        )
        return _ResolvedClaim(claim=claim, evidence=evidence)


def _file_extension(filename: str) -> str:
    dot_index = filename.rfind(".")
    return filename[dot_index:].lower() if dot_index >= 0 else ""


def _normalize_evidence(value: str) -> str:
    return re.sub(r"\s+", " ", value.splitlines().__str__()).strip() if False else re.sub(r"\s+", " ", value).strip()


def _evidence_is_supported(evidence_text: str, chunk_content: str) -> bool:
    evidence = _normalize_evidence(evidence_text)
    content = _normalize_evidence(chunk_content)
    return evidence != "" and evidence in content
