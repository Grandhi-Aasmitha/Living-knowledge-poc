from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.ai.client import AIProviderError


router = APIRouter(prefix="/api/curation", tags=["curation"])


class StartCurationResponse(BaseModel):
    workflow_id: str
    gap_id: str
    status: str
    question: str


class SubmitAnswerRequest(BaseModel):
    answer: str

    @field_validator("answer")
    @classmethod
    def answer_must_not_be_empty(cls, value: str) -> str:
        answer = value.strip()
        if answer == "":
            raise ValueError("answer must not be empty")
        return answer


class SubmitAnswerResponse(BaseModel):
    workflow_id: str
    status: str
    gap_id: str | None = None
    entity_id: str | None = None
    claim_id: str | None = None


def _get_workflow(request: Request) -> Any:
    workflow = getattr(request.app.state, "curation_workflow", None)
    if workflow is None:
        reason = getattr(request.app.state, "curation_unavailable_reason", "AI provider is unavailable")
        raise HTTPException(status_code=503, detail=reason)
    return workflow


def _raise_for_workflow_error(error: ValueError) -> None:
    message = str(error)
    if message.startswith("GAP_NOT_FOUND:"):
        raise HTTPException(status_code=404, detail="Knowledge gap not found") from error
    if message.startswith("GAP_NOT_OPEN:"):
        raise HTTPException(status_code=409, detail="Knowledge gap is not open") from error
    if message.startswith("WORKFLOW_NOT_WAITING:"):
        raise HTTPException(status_code=404, detail="Workflow is not waiting for an answer") from error
    if message.startswith("RELATED_ENTITY_NOT_FOUND:"):
        raise HTTPException(status_code=409, detail="Knowledge gap related entity was not found") from error
    if message.startswith("UNSUPPORTED_GAP_TYPE:"):
        raise HTTPException(status_code=409, detail="Knowledge gap type is not supported by Phase 3 curation") from error
    raise HTTPException(status_code=502, detail="Curation workflow failed") from error


@router.post("/gaps/{gap_id}/start", response_model=StartCurationResponse)
async def start_curation(gap_id: str, request: Request) -> StartCurationResponse:
    workflow = _get_workflow(request)
    workflow_id = str(uuid4())
    try:
        result = await workflow.start(workflow_id=workflow_id, gap_id=gap_id)
    except AIProviderError as error:
        raise HTTPException(status_code=502, detail="AI provider failed to generate structured output") from error
    except ValueError as error:
        _raise_for_workflow_error(error)

    if result.get("status") != "WAITING_FOR_HUMAN" or result.get("question") is None:
        raise HTTPException(status_code=502, detail="Curation workflow did not produce a question")

    return StartCurationResponse(
        workflow_id=result["workflow_id"],
        gap_id=result["gap_id"],
        status=result["status"],
        question=result["question"],
    )


@router.post("/workflows/{workflow_id}/answer", response_model=SubmitAnswerResponse)
async def submit_answer(
    workflow_id: str,
    body: SubmitAnswerRequest,
    request: Request,
) -> SubmitAnswerResponse:
    workflow = _get_workflow(request)
    try:
        if not await workflow.has_checkpoint(workflow_id):
            raise HTTPException(status_code=404, detail="Workflow not found")
        result = await workflow.answer(workflow_id=workflow_id, answer=body.answer)
    except AIProviderError as error:
        raise HTTPException(status_code=502, detail="AI provider failed to generate structured output") from error
    except ValueError as error:
        _raise_for_workflow_error(error)

    return SubmitAnswerResponse(
        workflow_id=workflow_id,
        status=result.get("status"),
        gap_id=result.get("gap_id"),
        entity_id=result.get("entity_id"),
        claim_id=result.get("claim_id"),
    )
