"""Answer a chat question: data first, then the knowledge base with the model."""

from app.core.config import Settings
from app.modules.chat.facts import answer_from_facts
from app.modules.chat.knowledge import Chunk, KnowledgeBase
from app.modules.chat.llm import LlmReply, OllamaClient
from app.modules.chat.prompts import build_messages
from app.modules.chat.schemas import ChatRequest, ChatResponse, Source


def retrieve(request: ChatRequest, knowledge: KnowledgeBase, top_k: int) -> list[Chunk]:
    ticket = request.context.ticket if request.context else None
    return knowledge.search(
        request.message, request.role, top_k, category=ticket.category if ticket else None
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
    request: ChatRequest,
    knowledge: KnowledgeBase,
    client: OllamaClient,
    settings: Settings,
    model: str | None = None,
) -> ChatResponse:
    """Questions about the user's day and tickets are answered from data, not by the model."""
    fact = answer_from_facts(request)
    if fact is not None:
        return ChatResponse(
            answer=fact.text,
            source_type="facts",
            sources=fact.sources,
            model=None,
            intent=fact.intent,
        )
    reply, chunks = generate(request, knowledge, client, settings, model=model)
    return ChatResponse(
        answer=reply.text,
        source_type="knowledge" if chunks else "model",
        sources=[Source(title=chunk.title, section=chunk.section) for chunk in chunks],
        model=model or settings.assistant_model,
    )
