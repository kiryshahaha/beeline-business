"""FastAPI entry point for the onboarding assistant service."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.modules.chat.knowledge import KnowledgeBase
from app.modules.chat.llm import OllamaClient
from app.modules.chat.router import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.knowledge = KnowledgeBase.from_dir(settings.knowledge_dir)
    app.state.llm = OllamaClient(settings.ollama_url, settings.llm_timeout_seconds)
    try:
        yield
    finally:
        app.state.llm.close()


app = FastAPI(
    title="Assistant Service",
    description="Чат-помощник для адаптации сотрудников: база знаний + малая LLM через Ollama.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(chat_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness check; does not call the model."""
    return {"status": "ok"}
