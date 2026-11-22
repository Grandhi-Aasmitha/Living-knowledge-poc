from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from app.ai.client import AIProviderError
from app.assessment.models import (
    AnswerAssessmentRequest, AssessmentView, ReviewAssessmentRequest, StartAssessmentRequest,
)


router = APIRouter(prefix="/api/assessments", tags=["assessments"])


def _workflow(request: Request):
    workflow = getattr(request.app.state, "assessment_workflow", None)
    if workflow is None:
        raise HTTPException(status_code=503, detail=getattr(request.app.state, "assessment_unavailable_reason", "Assessment AI is unavailable"))
    return workflow


def _failure(error: Exception) -> HTTPException:
    if isinstance(error, ValueError):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, AIProviderError):
        return HTTPException(status_code=502, detail="Assessment AI could not produce a valid evidence-backed finding")
    return HTTPException(status_code=503, detail="Knowledge base is unavailable")


@router.post("", response_model=AssessmentView)
async def start_assessment(body: StartAssessmentRequest, request: Request) -> AssessmentView:
    try:
        return await _workflow(request).start(str(uuid4()), body.namespace, body.source_application, body.target_application)
    except (ValueError, AIProviderError, OSError) as error:
        raise _failure(error) from error


@router.get("/{assessment_id}", response_model=AssessmentView)
async def get_assessment(assessment_id: str, request: Request) -> AssessmentView:
    result = await _workflow(request).get(assessment_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return result


@router.post("/{assessment_id}/answers", response_model=AssessmentView)
async def answer_assessment(assessment_id: str, body: AnswerAssessmentRequest, request: Request) -> AssessmentView:
    try:
        return await _workflow(request).answer(assessment_id, body.answer)
    except (ValueError, AIProviderError, OSError) as error:
        raise _failure(error) from error


@router.post("/{assessment_id}/review", response_model=AssessmentView)
async def review_assessment(assessment_id: str, body: ReviewAssessmentRequest, request: Request) -> AssessmentView:
    try:
        return await _workflow(request).review(assessment_id, body.decision, body.reviewer, body.comment)
    except (ValueError, AIProviderError, OSError) as error:
        raise _failure(error) from error
