"""Role-aware prompt assembly: rules in the system turn, retrieved facts next to the question."""

from datetime import datetime, time

from app.modules.chat.knowledge import Chunk
from app.modules.chat.schemas import ChatContext, ChatRequest, TicketContext, UserContext

ROLE_NAMES = {
    "worker": "исполнитель (выездной инженер)",
    "foreman": "начальник бригады",
    "observer": "диспетчер",
}
ESCALATION = {
    "worker": "уточните у диспетчера",
    "foreman": "уточните у диспетчера",
    "observer": "уточните у администратора системы",
}
STATUS_NAMES = {
    "planned": "Запланирована",
    "in_progress": "В работе",
    "completed": "Завершена",
    "wont_fix": "Не будет исправлено",
}

SYSTEM_PROMPT = """Ты — помощник в системе планирования выездных работ. \
Ты помогаешь сотруднику освоиться в системе и в работе.
Собеседник: {role_name}.

Правила:
1. Отвечай по-русски, коротко: 1–4 предложения или список до 4 пунктов.
2. Сначала смотри «Данные из системы»: там заявки, время, статусы и комментарии \
собеседника. Время, адреса и названия переписывай оттуда дословно.
3. Правила работы бери только из «Справки». Если справка говорит, что действие \
выполняет другая роль, так и ответь, кто его выполняет.
4. Никогда не описывай кнопки, меню и экраны и не придумывай суммы, сроки и правила.
5. Только если ответа нет ни в данных, ни в справке, ответь: \
«Не знаю — {escalation}»."""


def _format_datetime(value: datetime | None) -> str:
    return value.strftime("%d.%m %H:%M") if value else "не указано"


def _format_interval(start: datetime | None, end: datetime | None) -> str:
    if not start or not end:
        return "не назначено"
    if start.date() == end.date():
        return f"{start:%d.%m %H:%M}–{end:%H:%M}"
    return f"{_format_datetime(start)} – {_format_datetime(end)}"


def _format_time(value: time | None) -> str:
    return value.strftime("%H:%M") if value else "?"


def _format_user(user: UserContext, role: str) -> str:
    parts = [f"Пользователь: {user.name or 'без имени'}, роль: {ROLE_NAMES[role]}"]
    if user.workshift_start or user.workshift_end:
        parts.append(
            f"смена {_format_time(user.workshift_start)}–{_format_time(user.workshift_end)}"
        )
    if user.skills:
        parts.append("навыки: " + ", ".join(user.skills))
    if user.brigade:
        parts.append(f"бригада: {user.brigade}")
    return "; ".join(parts)


def _format_ticket(ticket: TicketContext) -> str:
    lines = [
        f"Заявка №{ticket.id} «{ticket.title}»",
        f"- Тип работ: {ticket.work_type}",
        f"- Статус: {STATUS_NAMES[ticket.status]}",
    ]
    if ticket.description:
        lines.append(f"- Описание: {ticket.description}")
    if ticket.address:
        lines.append(f"- Адрес: {ticket.address}")
    lines.append(
        f"- Окно визита: {_format_interval(ticket.visit_window_start, ticket.visit_window_end)}"
    )
    lines.append(
        f"- Плановое время: {_format_interval(ticket.planned_start_at, ticket.planned_end_at)}"
    )
    if ticket.estimated_duration_minutes:
        lines.append(f"- Ожидаемая длительность: {ticket.estimated_duration_minutes} мин")
    if ticket.assignees:
        lines.append("- Исполнители: " + ", ".join(ticket.assignees))
    if ticket.comments:
        lines.append("- Комментарии:")
        lines.extend(
            f"  - {_format_datetime(comment.created_at)}, {comment.author}: {comment.text}"
            for comment in ticket.comments
        )
    return "\n".join(lines)


def _format_ticket_row(number: int, ticket: TicketContext) -> str:
    interval = _format_interval(ticket.planned_start_at, ticket.planned_end_at)
    row = f"{number}. {interval} «{ticket.title}» — {STATUS_NAMES[ticket.status]}"
    if ticket.assignees:
        row += " — " + ", ".join(ticket.assignees)
    if ticket.address:
        row += f" — {ticket.address}"
    return row


def format_context(context: ChatContext, role: str) -> str:
    blocks = []
    if context.user:
        blocks.append(_format_user(context.user, role))
    if context.ticket:
        blocks.append("Открытая заявка:\n" + _format_ticket(context.ticket))
    if context.tickets:
        rows = [_format_ticket_row(n, t) for n, t in enumerate(context.tickets, start=1)]
        blocks.append(f"Заявки на день ({len(context.tickets)}):\n" + "\n".join(rows))
    return "\n\n".join(blocks)


def format_reference(chunks: list[Chunk]) -> str:
    return "\n\n".join(f"### {chunk.title}. {chunk.section}\n{chunk.text}" for chunk in chunks)


def build_messages(request: ChatRequest, chunks: list[Chunk]) -> list[dict[str, str]]:
    system = SYSTEM_PROMPT.format(
        role_name=ROLE_NAMES[request.role], escalation=ESCALATION[request.role]
    )
    parts = []
    if chunks:
        parts.append("Справка:\n" + format_reference(chunks))
    if request.context:
        context = format_context(request.context, request.role)
        if context:
            parts.append("Данные из системы:\n" + context)
    parts.append("Вопрос: " + request.message)

    messages = [{"role": "system", "content": system}]
    messages.extend({"role": m.role, "content": m.content} for m in request.history)
    messages.append({"role": "user", "content": "\n\n".join(parts)})
    return messages
