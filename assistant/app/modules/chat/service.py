"""Answer a chat question: retrieve sections, assemble the prompt, call the model."""

from app.core.config import Settings
from app.modules.chat.knowledge import Chunk, KnowledgeBase
from app.modules.chat.llm import LlmReply, OllamaClient
from app.modules.chat.prompts import build_messages
from app.modules.chat.schemas import ChatRequest, ChatResponse, Source


def retrieve(request: ChatRequest, knowledge: KnowledgeBase, top_k: int) -> list[Chunk]:
    ticket = request.context.ticket if request.context else None
    return knowledge.search(
        request.message, request.role, top_k, work_type=ticket.work_type if ticket else None
    )


def generate(
    request: ChatRequest,
    knowledge: KnowledgeBase,
    client: OllamaClient,
    settings: Settings,
    model: str | None = None,
) -> tuple[LlmReply, list[Chunk]]:
    chunks = retrieve(request, knowledge, settings.retrieval_top_k)
    reply = client.chat(
        model or settings.assistant_model,
        build_messages(request, chunks),
        temperature=settings.llm_temperature,
        num_ctx=settings.llm_num_ctx,
        max_tokens=settings.llm_max_tokens,
        num_thread=settings.llm_num_thread,
    )
    return reply, chunks


def answer(
    request: ChatRequest, knowledge: KnowledgeBase, client: OllamaClient, settings: Settings
) -> ChatResponse:
    reply, chunks = generate(request, knowledge, client, settings)
    return ChatResponse(
        answer=reply.text,
        sources=[Source(title=chunk.title, section=chunk.section) for chunk in chunks],
        model=settings.assistant_model,
    )
