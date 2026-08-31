from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.ai.client import AIProviderError
from app.assistant.models import AssistantQuestionRequest, AssistantResponse
from app.assistant.service import AssistantValidationError


router = APIRouter(prefix="/api/assistant", tags=["assistant"])


def _get_assistant_service(request: Request) -> Any:
    service = getattr(request.app.state, "knowledge_assistant_service", None)
    if service is None:
        reason = getattr(request.app.state, "knowledge_assistant_unavailable_reason", "AI provider is unavailable")
        raise HTTPException(status_code=503, detail=reason)
    return service


@router.post("/ask", response_model=AssistantResponse)
async def ask_assistant(payload: AssistantQuestionRequest, request: Request) -> AssistantResponse:
    service = _get_assistant_service(request)
    try:
        return await service.ask(payload.question, payload.namespace)
    except AssistantValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except AIProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=503, detail="Neo4j is unavailable") from error
