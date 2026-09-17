"""HTTP endpoint for the onboarding chat. Authorization stays in the main backend."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.config import Settings, get_settings
from app.modules.chat import service
from app.modules.chat.llm import LlmUnavailableError
from app.modules.chat.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("", response_model=ChatResponse, responses={503: {"description": "Модель недоступна"}})
def chat(
    data: ChatRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChatResponse:
    """Ответить на вопрос пользователя по базе знаний и контексту из бэкенда."""
    try:
        return service.answer(data, request.app.state.knowledge, request.app.state.llm, settings)
    except LlmUnavailableError as error:
        raise HTTPException(status_code=503, detail="Модель недоступна") from error
