"""Role-aware prompt assembly: rules in the system turn, retrieved facts next to the question."""

from datetime import date

from app.modules.chat.facts import (
    author_label,
    change_phrase,
    hm,
    interval,
    state_name,
    ticket_name,
    when,
)
from app.modules.chat.knowledge import Chunk
from app.modules.chat.schemas import (
    ChatContext,
    ChatRequest,
    DayContext,
    ShiftContext,
    TicketContext,
)

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
CATEGORY_NAMES = {
    "emergency": "авария",
    "connection": "подключение",
    "repair": "ремонт у клиента",
    "additional": "дозаказ оборудования",
}

SYSTEM_PROMPT = """Ты — помощник в системе планирования выездных работ. \
Ты помогаешь сотруднику освоиться в системе и в работе.
Собеседник: {role_name}.

Правила:
1. Отвечай по-русски, коротко: 1–4 предложения или список до 4 пунктов.
2. Время, адреса, статусы и названия заявок бери только из «Данных из системы» \
и переписывай дословно. Ничего не считай и не придумывай сам.
3. Правила работы бери только из «Справки». Если справка говорит, что действие \
выполняет другая роль, так и ответь, кто его выполняет.
4. Никогда не описывай кнопки, меню и экраны, которых нет в справке, \
и не придумывай суммы, сроки и правила.
5. Не смешивай сообщение о проблеме со сменой статуса заявки. Если справка \
запрещает исполнителю менять статус, не советуй отменять заявку, снимать её \
или назначать другому исполнителю.
6. Не считай молчание клиента или закрытую дверь его отказом. Не выбирай \
причину проблемы за исполнителя: если факт неясен, назови подходящие варианты \
из справки и попроси уточнить ситуацию.
7. Только если ответа нет ни в данных, ни в справке, ответь: \
«Не знаю — {escalation}»."""


def _shift_line(shift: ShiftContext | None, label: str) -> str | None:
    if shift is None:
        return None
    if not shift.is_working_day or shift.start is None or shift.end is None:
        return f"{label}: выходной"
    return f"{label}: смена {hm(shift.start)}–{hm(shift.end)}"


def _format_day(day: DayContext, tomorrow: ShiftContext | None) -> list[str]:
    blocks = []
    worker = day.worker
    head = []
    if worker:
        name = " ".join(part for part in (worker.name, worker.surname) if part)
        head.append(f"Исполнитель: {name or 'без имени'}")
        if worker.brigade:
            head.append(f"бригада: {worker.brigade.name}")
        if worker.office:
            head.append(f"офис: {worker.office.name}")
    head.extend(
        line
        for line in (
            _shift_line(day.shift, f"сегодня ({day.date:%d.%m})"),
            _shift_line(tomorrow, "завтра"),
        )
        if line
    )
    state = day.day_state
    if state and not state.available:
        until = f" до {when(state.unavailable_until, day.date)}" if state.unavailable_until else ""
        head.append(f"сейчас недоступен{until}" + (f" ({state.reason})" if state.reason else ""))
    if head:
        blocks.append("; ".join(head))
    if day.summary:
        s = day.summary
        blocks.append(
            f"Заявок сегодня: {s.total} (выполнено {s.completed}, ждут подтверждения "
            f"{s.awaiting_confirmation}, в работе {s.in_progress}, осталось {s.remaining}, "
            f"отменено {s.cancelled})"
        )
    if day.tickets:
        rows = []
        tickets = sorted(day.tickets, key=lambda t: (t.sequence is None, t.sequence or 0, t.id))
        for number, ticket in enumerate(tickets, start=1):
            planned = interval(ticket.planned_start_at, ticket.planned_end_at, day.date)
            row = f"{number}. " + (f"{planned} " if planned else "")
            row += f"{ticket_name(ticket)} — {state_name(ticket)}"
            if ticket.id == day.current_ticket_id:
                row += " (текущая)"
            elif ticket.id == day.next_ticket_id:
                row += " (следующая)"
            if ticket.location and ticket.location.address:
                row += f" — {ticket.location.address}"
            if ticket.last_change and ticket.last_change.reason_text:
                row += f" — изменение: {ticket.last_change.reason_text}"
            rows.append(row)
        blocks.append("Заявки на день по порядку:\n" + "\n".join(rows))
    if day.removed_tickets:
        rows = [
            f"- №{item.ticket_id} «{item.title}»: {item.reason_text or 'причина не указана'}"
            for item in day.removed_tickets
        ]
        blocks.append("Сняты с исполнителя сегодня:\n" + "\n".join(rows))
    return blocks


def _format_ticket(ticket: TicketContext, today: date | None) -> str:
    lines = [f"Заявка {ticket_name(ticket)}"]
    if ticket.category:
        lines.append(f"- Категория: {CATEGORY_NAMES.get(ticket.category, ticket.category)}")
    if ticket.work_type:
        lines.append(f"- Вид работ: {ticket.work_type}")
    lines.append(f"- Статус: {state_name(ticket)}")
    if ticket.description:
        lines.append(f"- Описание: {ticket.description}")
    if ticket.location and ticket.location.address:
        lines.append(f"- Адрес: {ticket.location.address}")
    window = interval(ticket.visit_window_start, ticket.visit_window_end, today)
    lines.append(f"- Окно клиента: {window or 'не указано'}")
    planned = interval(ticket.planned_start_at, ticket.planned_end_at, today)
    lines.append(f"- Плановое время работ: {planned or 'не назначено'}")
    if ticket.planned_arrival_at:
        lines.append(f"- Прибытие по плану: {when(ticket.planned_arrival_at, today)}")
    if ticket.estimated_duration_minutes:
        lines.append(f"- Ожидаемая длительность: {ticket.estimated_duration_minutes} мин")
    appliances = ticket.appliances or ticket.required_appliances
    if appliances:
        items = ", ".join(f"{a.appliance_name} — {a.quantity} {a.unit or 'шт'}" for a in appliances)
        lines.append(f"- Оборудование: {items}")
    if ticket.comments:
        lines.append("- Комментарии:")
        lines.extend(
            f"  - {when(c.created_at, today) if c.created_at else ''} {author_label(c)}: {c.text}"
            for c in ticket.comments[-10:]
        )
    if ticket.changes:
        lines.append("- История изменений:")
        lines.extend(
            f"  - {when(c.at, today)}: {change_phrase(c, today)}"
            + (f" — {c.reason_text}" if c.reason_text else "")
            for c in ticket.changes[-10:]
        )
    return "\n".join(lines)


def format_context(context: ChatContext, role: str) -> str:
    blocks = [f"Роль собеседника: {ROLE_NAMES[role]}"]
    today = context.day.date if context.day else None
    if context.day:
        blocks.extend(_format_day(context.day, context.tomorrow_shift))
    if context.ticket:
        blocks.append("Открытая заявка:\n" + _format_ticket(context.ticket, today))
    return "\n\n".join(blocks) if len(blocks) > 1 else ""


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
