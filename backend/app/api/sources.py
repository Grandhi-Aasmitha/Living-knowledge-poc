import logging
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.ai.client import AIProviderError
from app.documents.chunker import ChunkLimitExceededError
from app.documents.parsers import DocumentParseError, NoExtractableTextError, UnsupportedDocumentTypeError
from app.documents.storage import UploadTooLargeError
from app.services.file_ingestion_service import NoExplicitRelationshipsError


router = APIRouter(prefix="/api/sources/files", tags=["sources"])
logger = logging.getLogger(__name__)


class EntityResolutionSummaryResponse(BaseModel):
    observed_name: str
    observed_type: str
    action: Literal["MATCH", "CREATE", "NEEDS_REVIEW"]
    canonical_entity_id: str | None = None
    canonical_name: str | None = None
    reason: str | None = None
    alias_learned: bool = False


class IngestionResponse(BaseModel):
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
    unresolved_terms: list[str]
    entity_resolutions: list[EntityResolutionSummaryResponse] = Field(default_factory=list)


class SourceDocumentResponse(BaseModel):
    id: str
    title: str
    filename: str
    namespace: str
    latest_version: int
    current_content_hash: str
    updated_at: str


def _get_ingestion_service(request: Request) -> Any:
    service = getattr(request.app.state, "file_ingestion_service", None)
    if service is None:
        reason = getattr(request.app.state, "file_ingestion_unavailable_reason", "AI provider is unavailable")
        raise HTTPException(status_code=503, detail=reason)
    return service


@router.post("", response_model=IngestionResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    namespace: str = Form("tstvs"),
    force: bool = Form(False),
) -> IngestionResponse:
    service = _get_ingestion_service(request)
    try:
        content = await file.read()
        result = await service.ingest(content=content, original_filename=file.filename or "", namespace=namespace, force=force)
    except UnsupportedDocumentTypeError as error:
        logger.info("Upload rejected unsupported_type namespace=%s", namespace)
        raise HTTPException(status_code=400, detail=str(error)) from error
    except UploadTooLargeError as error:
        logger.info("Upload rejected too_large namespace=%s", namespace)
        raise HTTPException(status_code=413, detail=str(error)) from error
    except (DocumentParseError, NoExtractableTextError, ChunkLimitExceededError) as error:
        logger.info("Upload rejected unprocessable namespace=%s reason=%s", namespace, str(error))
        raise HTTPException(status_code=422, detail=str(error)) from error
    except NoExplicitRelationshipsError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except AIProviderError as error:
        logger.warning("Upload failed during AI extraction namespace=%s provider_error=%s", namespace, str(error))
        raise HTTPException(status_code=502, detail="AI provider failed to generate structured output") from error
    except ValueError as error:
        logger.info("Upload rejected validation namespace=%s reason=%s", namespace, str(error))
        raise HTTPException(status_code=422, detail="File ingestion failed validation") from error

    logger.info(
        "Upload completed document_id=%s version_id=%s status=%s namespace=%s chunks=%d claims_created=%d claims_reused=%d evidence_created=%d claims_rejected=%d",
        result.document_id,
        result.version_id,
        result.status,
        namespace,
        result.chunks_processed,
        result.claims_created,
        result.claims_reused,
        result.evidence_created,
        result.claims_rejected,
    )
    return IngestionResponse(**asdict(result))


@router.get("", response_model=list[SourceDocumentResponse])
async def list_files(request: Request) -> list[SourceDocumentResponse]:
    repository = getattr(request.app.state, "document_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Document repository is unavailable")
    documents = await repository.list_documents()
    return [
        SourceDocumentResponse(
            id=document.id,
            title=document.title,
            filename=document.filename,
            namespace=document.namespace,
            latest_version=document.latest_version,
            current_content_hash=document.current_content_hash,
            updated_at=document.updated_at.isoformat(),
        )
        for document in documents
    ]
