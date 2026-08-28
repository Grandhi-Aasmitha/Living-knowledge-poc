from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.ai.client import AIProviderError
from app.documents.chunker import ChunkLimitExceededError
from app.documents.parsers import NoExtractableTextError, UnsupportedDocumentTypeError
from app.documents.storage import UploadTooLargeError


router = APIRouter(prefix="/api/sources/files", tags=["sources"])


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


class SourceDocumentResponse(BaseModel):
    id: str
    title: str
    filename: str
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
) -> IngestionResponse:
    service = _get_ingestion_service(request)
    try:
        content = await file.read()
        result = await service.ingest(content=content, original_filename=file.filename or "", namespace=namespace)
    except UnsupportedDocumentTypeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except UploadTooLargeError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except (NoExtractableTextError, ChunkLimitExceededError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except AIProviderError as error:
        raise HTTPException(status_code=502, detail="AI provider failed to generate structured output") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail="File ingestion failed validation") from error

    return IngestionResponse(**result.__dict__)


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
            latest_version=document.latest_version,
            current_content_hash=document.current_content_hash,
            updated_at=document.updated_at.isoformat(),
        )
        for document in documents
    ]
