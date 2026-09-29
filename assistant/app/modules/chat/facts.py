"""Answers about the user's shift and tickets, assembled from backend data.

The model never computes times, counts or reasons: a question is matched against
hand-written patterns and, when the context holds the data, the answer is built from it.
Anything unrecognised returns None and the caller asks the model with the same context.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.modules.chat.knowledge import tokenize
from app.modules.chat.schemas import (
    ChatRequest,
    CommentContext,
    DayContext,
    RemovedTicket,
    ShiftContext,
    Source,
    TicketChange,
    TicketContext,
)

MOSCOW = timezone(timedelta(hours=3))

STATE_NAMES = {
    "waiting_assignment": "ждёт назначения",
    "assigned": "назначена",
    "dispatched": "передана вам",
    "en_route": "в пути",
    "in_progress": "в работе",
    "completed": "завершена",
    "cancelled": "отменена",
}
ROLE_LABELS = {"observer": "диспетчер", "foreman": "бригадир", "worker": "исполнитель"}
ACTIVE_STATES = {"assigned", "dispatched", "en_route"}
CHANGE_KINDS = {
    "rescheduled",
    "reassigned",
    "unassigned",
    "window_changed",
    "redirected",
    "cancelled",
    "completion_rejected",
    "delayed",
    "reopened",
}
NO_REASON = "причина в системе не указана — уточните у диспетчера"


@dataclass(frozen=True)
class FactAnswer:
    intent: str
    text: str
    sources: list[Source]


# --- Text helpers ---


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w№:\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        word = one
    elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        word = few
    else:
        word = many
    return f"{n} {word}"


def _local(value: datetime) -> datetime:
    return value.astimezone(MOSCOW)


def hm(value: datetime) -> str:
    return _local(value).strftime("%H:%M")


def _day_prefix(value: datetime, today: date | None) -> str:
    day = _local(value).date()
    if today is None or day == today:
        return ""
    if day == today + timedelta(days=1):
        return "завтра "
    if day == today - timedelta(days=1):
        return "вчера "
    return f"{day:%d.%m} "


def when(value: datetime, today: date | None) -> str:
    prefix = _day_prefix(value, today)
    return f"{prefix}в {hm(value)}" if prefix else hm(value)


def at_time(value: datetime, today: date | None) -> str:
    """«в 09:10», «завтра в 15:00»."""
    text = when(value, today)
    return text if " в " in text else f"в {text}"


def interval(start: datetime | None, end: datetime | None, today: date | None) -> str | None:
    if start is None:
        return None
    text = f"{_day_prefix(start, today)}{hm(start)}"
    if end is not None:
        text += f"–{hm(end)}"
    return text


def ticket_name(ticket: TicketContext) -> str:
    return f"№{ticket.id} «{ticket.title}»"


def state_name(ticket: TicketContext) -> str:
    if ticket.state == "completed" and ticket.completion_review:
        review = ticket.completion_review
        if review.state == "pending":
            return "завершена, ждёт подтверждения диспетчера"
        if review.state == "confirmed":
            return "завершена, диспетчер подтвердил"
    return STATE_NAMES.get(ticket.state or "", "статус неизвестен")


# --- Intent patterns ---


@dataclass(frozen=True)
class Rule:
    intent: str
    require: tuple[re.Pattern, ...]
    exclude: re.Pattern | None = None

    def matches(self, text: str) -> bool:
        if self.exclude is not None and self.exclude.search(text):
            return False
        return all(pattern.search(text) for pattern in self.require)


def _rule(intent: str, *require: str, exclude: str | None = None) -> Rule:
    return Rule(
        intent,
        tuple(re.compile(pattern) for pattern in require),
        re.compile(exclude) if exclude else None,
    )


# Order is priority: the first matching rule wins.
RULES = (
    _rule(
        "greeting",
        r"^(привет|здравствуй|здравствуйте|добрый (день|вечер)|доброе утро|хай|салам)\b",
        exclude=r"заявк|смен|почему|сколько|когда|куда|как\b|что\b|где\b",
    ),
    _rule(
        "why_changed",
        r"\b(почему|зачем|из за чего|по какой причине|за что|с чего)\b|причин[аыу]?\b",
        r"перенес|перенос|сдвин|поменял|изменил|измени|снял|сняли|забрал|убрал|отдал|передал"
        r"|переназнач|отменил|отменен|отмен|переставил|вернул|позже|раньше|другому",
    ),
    _rule(
        "shift",
        r"\bсмен[аеуы]?\b|до скольки (я |мне )?(работаю|сегодня|завтра|у меня)"
        r"|во сколько (я |мне )?(заканчиваю|начинаю|кончаю|выхожу|на работу|на смену)"
        r"|когда (я |мне )?(заканчиваю|начинаю|кончаю|освобожусь|домой|на работу)"
        r"|рабоч(ий|его|ее) (день|время|график)|\bграфик\b|\bвыходн"
        r"|работаю (ли )?(я )?(завтра|сегодня)|(завтра|сегодня) работаю|(мне )?завтра на работу",
        exclude=r"\b(поменять|изменить|сменить|перенести|перевести|взять|оформить|отпроситься"
        r"|поменяться|обменяться)\b|смен[аеуы]? (статус|заявк|исполнител)",
    ),
    _rule(
        "day_count",
        r"(?<!во )(?<!в )\bсколько\b|\bмного\b|\bколичество\b",
        r"заяв|задач|вызов|адрес|точк|выезд|клиент|объект|работ|осталос|сделал|выполнил|закрыл",
        exclude=r"сколько (стоит|длится|времени|минут|ехать|идти|по времени|платят|получа|денег)"
        r"|норматив",
    ),
    _rule(
        "next_ticket",
        r"следующ|\bдальше\b|\bпотом\b|после (этой|нее|того|заявк|[а-я]{3,})"
        r"|куда (мне )?(теперь|сейчас|щас|потом|ехать после)|что (у меня )?(дальше|потом)",
        exclude=r"(что|как) (мне )?(делать|сделать|нажать|писать|написать|ставить) "
        r"(дальше|потом|после)|после (завершени|закрыти|того как|выполнени)"
        r"|\b(почему|зачем)\b",
    ),
    _rule(
        "ticket_time",
        r"во сколько|\bкогда\b|к скольки|к какому времени|в какое время|до скольки|\bвремя\b",
        r"ехать|приехать|быть|надо|нужно|начин|заявк|клиент|визит|окн|выезж|прибыть|выезд"
        r"|ждет|ждут|успеть",
        exclude=r"зарплат|аванс|выплат|отпуск|обед|(?<!во )сколько (ехать|по времени)"
        r"|(ставить|поставить|нажать|переводить|перевести|писать|написать|исправить)",
    ),
    _rule(
        "ticket_status",
        r"статус|закрыт|завершен|отменен|подтвердил|подтвержд|приняли|принята|засчитал",
        exclude=r"(как|какой|что|когда|можно|могу|нужно|надо) .{0,25}(поставить|перевести|нажать"
        r"|выбрать|ставить|сменить|изменить|закрыть|завершить|подтвердить)|\bкто\b|\bчто значит"
        r"|что (мне )?(делать|нажать)",
    ),
    _rule(
        "ticket_equipment",
        r"что (мне )?(взять|брать|нужно взять|надо взять|с собой|понадобится)"
        r"|оборудован|какой (роутер|терминал|модем)|какие (материал|запчаст|устройств)",
        exclude=r"(как|где|куда|можно ли|кто) .{0,25}(получить|взять|сдать|вернуть|списать"
        r"|оформить|выдает|выдают)|сколько стоит",
    ),
    _rule(
        "ticket_notes",
        r"что (важно|нужно|надо|стоит) (знать|учесть)|комментари|заметк|что (написал|пишут|сказал)"
        r"|особенност|что по (заявке|этой заявке|клиенту)|подробност|описани|что за заявка",
        exclude=r"(как|можно ли|могу ли|нужно ли|надо ли|где) .{0,25}(написать|оставить|исправить"
        r"|редактир|удалить|писать|добавить)|пароль",
    ),
    _rule(
        "ticket_address",
        r"\bадрес|подъезд|\bэтаж|квартир|куда (мне )?ехать|где (находится|клиент|объект|дом)"
        r"|на какой улиц|какая улица",
        exclude=r"где (посмотреть|увидеть)|как (изменить|исправить|поменять|найти в)",
    ),
    _rule(
        "current_ticket",
        r"(на какой|какая|какую|какой) (я |у меня )?(сейчас |щас |теперь )?(заявк|задач)"
        r"|текущ(ая|ую|ей) (заявк|задач)|где я сейчас|что я сейчас делаю"
        r"|на какой я (заявке|задаче|адресе)",
    ),
    _rule(
        "day_list",
        r"(какие|что|список|все|покажи|перечисли) .{0,30}(заявк|задач|вызов|адрес|выезд)"
        r"|мой маршрут|маршрут на (сегодня|день)|план на (сегодня|день)"
        r"|что у меня (сегодня|на сегодня|по плану)",
        exclude=r"\b(как|где|почему)\b",
    ),
)


def _match(text: str) -> str | None:
    return next((rule.intent for rule in RULES if rule.matches(text)), None)


def detect_intents(message: str) -> list[str]:
    """«Какая смена и сколько заявок?» asks two things; each clause gets its own answer."""
    text = normalize(message)
    clauses = [c for c in re.split(r"\s+и\s+|\s+а еще\s+|\s+а также\s+", text) if c]
    found = list(dict.fromkeys(i for i in map(_match, clauses) if i))
    if len(found) > 1:
        return [intent for intent in found if intent != "greeting"]
    whole = _match(text)
    return [whole] if whole else []


def detect_intent(message: str) -> str | None:
    intents = detect_intents(message)
    return intents[0] if intents else None


# --- Finding the ticket a question is about ---


def _stems(text: str) -> set[str]:
    """Stem prefixes: «проверки» and «проверить» stem differently but share «прове»."""
    return {stem[:5] for stem in tokenize(text) if len(stem) >= 4}


_GENERIC_STEMS = frozenset(
    _stems(
        "заявка заявку заявки заявке задача клиент клиенту сегодня завтра работа работу адрес "
        "следующая следующую после ехать время когда сколько какой какая почему перенесли "
        "мне меня мой моя сейчас потом дальше куда статус взять собой нужно надо важно знать "
        "комментарии комментарий улица дом подъезд этаж квартира номер эта этой эту"
    )
)


def _ticket_stems(ticket: TicketContext) -> set[str]:
    words = ticket.title
    if ticket.location and ticket.location.street:
        words += " " + ticket.location.street
    return _stems(words) - _GENERIC_STEMS


def _find_by_reference(text: str, tickets: list[TicketContext]) -> TicketContext | None:
    number = re.search(r"(?:№|номер|заявк[а-я]*)\s*(\d{1,7})\b", text)
    if number:
        wanted = int(number.group(1))
        return next((ticket for ticket in tickets if ticket.id == wanted), None)
    query = _stems(text) - _GENERIC_STEMS
    if not query:
        return None
    scored = sorted(
        ((len(query & _ticket_stems(ticket)), ticket) for ticket in tickets),
        key=lambda item: -item[0],
    )
    if not scored or scored[0][0] == 0:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][1]


def _merge(open_ticket: TicketContext, day_ticket: TicketContext) -> TicketContext:
    """The open card has comments and changes; the day entry has order and arrival."""
    update = {
        field: getattr(day_ticket, field)
        for field in (
            "sequence",
            "planned_arrival_at",
            "required_appliances",
            "comments_count",
            "completion_review",
            "last_change",
        )
        if not getattr(open_ticket, field)
    }
    return open_ticket.model_copy(update=update)


class Facts:
    """Everything a question can be answered from, in one place."""

    def __init__(self, request: ChatRequest):
        context = request.context
        self.role = request.role
        self.day: DayContext | None = context.day if context else None
        self.tomorrow_shift: ShiftContext | None = context.tomorrow_shift if context else None
        self.open_ticket: TicketContext | None = context.ticket if context else None
        self.today: date | None = self.day.date if self.day else None
        day_tickets = self.day.tickets if self.day else []
        self.tickets = sorted(
            day_tickets, key=lambda t: (t.sequence is None, t.sequence or 0, t.id)
        )
        if self.open_ticket:
            match = next((t for t in self.tickets if t.id == self.open_ticket.id), None)
            merged = _merge(self.open_ticket, match) if match else self.open_ticket
            self.open_ticket = merged
            self.tickets = [merged if t.id == merged.id else t for t in self.tickets]

    def by_id(self, ticket_id: int | None) -> TicketContext | None:
        return next((t for t in self.tickets if t.id == ticket_id), None)

    def candidates(self) -> list[TicketContext]:
        if self.tickets:
            return self.tickets
        return [self.open_ticket] if self.open_ticket else []

    def current(self) -> TicketContext | None:
        if not self.day:
            return None
        ticket = self.by_id(self.day.current_ticket_id)
        if ticket:
            return ticket
        return next((t for t in self.tickets if t.state in {"en_route", "in_progress"}), None)

    def next_after(self, ticket: TicketContext | None) -> TicketContext | None:
        if ticket is None:
            if self.day and self.day.next_ticket_id:
                return self.by_id(self.day.next_ticket_id)
            return next((t for t in self.tickets if t.state in {"assigned", "dispatched"}), None)
        index = self.tickets.index(ticket) if ticket in self.tickets else -1
        return next(
            (t for t in self.tickets[index + 1 :] if t.state in {"assigned", "dispatched"}),
            None,
        )

    def target(self, text: str) -> TicketContext | None:
        referenced = _find_by_reference(text, self.candidates())
        if referenced:
            return referenced
        if self.day and re.search(r"следующ", text):
            return self.next_after(self.current())
        if self.day and re.search(r"текущ|сейчас|щас", text):
            return self.current()
        if self.open_ticket:
            return self.open_ticket
        return self.current() or self.next_after(None)


def _source(section: str) -> list[Source]:
    return [Source(title="Данные системы", section=section)]


# --- Answer builders; each returns None when the data needed is missing ---


def _greeting(facts: Facts, text: str) -> FactAnswer | None:
    if facts.role == "worker":
        example = "«Куда мне дальше?» или «Почему перенесли заявку?»"
        topics = "какая у вас смена, куда ехать дальше, что по заявке и почему её перенесли"
    else:
        example = "«Как подтвердить завершение заявки?»"
        topics = "как работать в системе и что происходит с открытой заявкой"
    return FactAnswer(
        "greeting",
        f"Здравствуйте! Подскажу, {topics}. Спросите, например: {example}",
        [],
    )


def _shift_text(shift: ShiftContext, label: str) -> str:
    if not shift.is_working_day or shift.start is None or shift.end is None:
        return f"{label} у вас выходной по графику."
    end = hm(shift.end)
    if _local(shift.end).date() > _local(shift.start).date():
        end += " следующего дня"
    return f"{label} ваша смена с {hm(shift.start)} до {end}."


def _shift(facts: Facts, text: str) -> FactAnswer | None:
    if "завтра" in text:
        if facts.tomorrow_shift is None:
            return None
        return FactAnswer("shift", _shift_text(facts.tomorrow_shift, "Завтра"), _source("Смена"))
    if not facts.day or facts.day.shift is None:
        return None
    answer = _shift_text(facts.day.shift, "Сегодня")
    state = facts.day.day_state
    if state and not state.available:
        until = (
            f" до {when(state.unavailable_until, facts.today)}" if state.unavailable_until else ""
        )
        reason = f": {state.reason}" if state.reason else ""
        answer += f" Сейчас вы отмечены недоступным{until}{reason}."
    return FactAnswer("shift", answer, _source("Смена"))


def _day_count(facts: Facts, text: str) -> FactAnswer | None:
    if not facts.day or facts.day.summary is None:
        return None
    if "завтра" in text:
        return FactAnswer(
            "day_count",
            "План на завтра я пока не вижу — он появится после публикации.",
            _source("Мой день"),
        )
    s = facts.day.summary
    if s.total == 0:
        return FactAnswer("day_count", "На сегодня заявок нет.", _source("Мой день"))
    parts = []
    if s.completed:
        parts.append(f"выполнено {s.completed}")
    if s.awaiting_confirmation:
        parts.append(f"ждут подтверждения диспетчера {s.awaiting_confirmation}")
    if s.in_progress:
        parts.append(f"в работе {s.in_progress}")
    parts.append(f"осталось {s.remaining}")
    if s.cancelled:
        parts.append(f"отменено {s.cancelled}")
    answer = f"Сегодня у вас {plural(s.total, 'заявка', 'заявки', 'заявок')}: " + ", ".join(parts)
    return FactAnswer("day_count", answer + ".", _source("Мой день"))


def _ticket_line(ticket: TicketContext, today: date | None) -> str:
    planned = interval(ticket.planned_start_at, ticket.planned_end_at, today)
    prefix = f"{planned} " if planned else ""
    return f"{prefix}{ticket_name(ticket)} — {state_name(ticket)}"


def _day_list(facts: Facts, text: str) -> FactAnswer | None:
    if not facts.day:
        return None
    tickets = facts.tickets
    if re.search(r"не начат|остал|ещ[е]? не|впереди|предстоит", text):
        tickets = [t for t in tickets if t.state in ACTIVE_STATES]
        title = "Осталось"
    elif re.search(r"сделал|выполнил|закрыл|завершил|готов", text):
        tickets = [t for t in tickets if t.state == "completed"]
        title = "Выполнено"
    else:
        title = "Ваши заявки на сегодня"
    if not tickets:
        return FactAnswer("day_list", "Таких заявок на сегодня нет.", _source("Мой день"))
    lines = [f"{n}. {_ticket_line(t, facts.today)}" for n, t in enumerate(tickets, start=1)]
    answer = f"{title} ({len(tickets)}):\n" + "\n".join(lines)
    return FactAnswer("day_list", answer, _source("Мой день"))


def _visit_text(ticket: TicketContext, today: date | None) -> str:
    parts = []
    planned = interval(ticket.planned_start_at, ticket.planned_end_at, today)
    if planned:
        parts.append(f"по плану {planned}")
    if ticket.location and ticket.location.address:
        parts.append(f"адрес: {ticket.location.address}")
    return ", ".join(parts)


def _next_ticket(facts: Facts, text: str) -> FactAnswer | None:
    if not facts.day:
        return None
    anchor = None
    after = re.search(r"после (.+)$", text)
    if after and not re.match(r"(этой|нее|того|текущ)", after.group(1)):
        anchor = _find_by_reference(after.group(1), facts.tickets)
        if anchor is None:
            return None
    elif re.search(r"куда (мне )?(теперь|сейчас|щас)", text):
        current = facts.current()
        if current and current.state == "en_route":
            answer = f"Вы в пути на заявку {ticket_name(current)}"
            if current.planned_arrival_at:
                answer += f", прибытие по плану {when(current.planned_arrival_at, facts.today)}"
            visit = _visit_text(current, facts.today)
            return FactAnswer(
                "next_ticket",
                f"{answer}. {visit[0].upper() + visit[1:]}." if visit else answer + ".",
                _source(f"Заявка №{current.id}"),
            )
    else:
        anchor = facts.current()
    ticket = facts.next_after(anchor)
    if ticket is None:
        return FactAnswer("next_ticket", "Больше заявок на сегодня нет.", _source("Мой день"))
    answer = f"Следующая заявка — {ticket_name(ticket)}"
    visit = _visit_text(ticket, facts.today)
    if visit:
        answer += f", {visit}"
    return FactAnswer("next_ticket", answer + ".", _source(f"Заявка №{ticket.id}"))


def _current_ticket(facts: Facts, text: str) -> FactAnswer | None:
    if not facts.day:
        return None
    ticket = facts.current()
    if ticket is None:
        upcoming = facts.next_after(None)
        answer = "Сейчас у вас нет заявки в работе."
        if upcoming:
            planned = interval(upcoming.planned_start_at, upcoming.planned_end_at, facts.today)
            answer += f" Следующая — {ticket_name(upcoming)}" + (f", {planned}" if planned else "")
            answer += "."
        return FactAnswer("current_ticket", answer, _source("Мой день"))
    lead = "Вы в пути на заявку" if ticket.state == "en_route" else "Сейчас вы на заявке"
    answer = f"{lead} {ticket_name(ticket)}"
    visit = _visit_text(ticket, facts.today)
    if visit:
        answer += f", {visit}"
    return FactAnswer("current_ticket", answer + ".", _source(f"Заявка №{ticket.id}"))


def _ticket_time(facts: Facts, text: str) -> FactAnswer | None:
    ticket = facts.target(text)
    if ticket is None:
        return None
    parts = []
    if ticket.planned_start_at:
        start = f"Плановое начало работ по заявке {ticket_name(ticket)} — "
        start += when(ticket.planned_start_at, facts.today)
        if ticket.planned_end_at:
            start += f", окончание {hm(ticket.planned_end_at)}"
        parts.append(start + ".")
        if ticket.planned_arrival_at:
            parts.append(f"Приехать по плану к {hm(ticket.planned_arrival_at)}.")
    else:
        parts.append(f"Время по заявке {ticket_name(ticket)} пока не назначено.")
    window = interval(ticket.visit_window_start, ticket.visit_window_end, facts.today)
    if window:
        parts.append(f"Окно клиента: {window}.")
    return FactAnswer("ticket_time", " ".join(parts), _source(f"Заявка №{ticket.id}"))


def _ticket_address(facts: Facts, text: str) -> FactAnswer | None:
    ticket = facts.target(text)
    if ticket is None or not ticket.location or not ticket.location.address:
        return None
    answer = f"Адрес заявки {ticket_name(ticket)}: {ticket.location.address}."
    if ticket.location.entrance_number is None and re.search(r"подъезд", text):
        answer += " Подъезд не указан — уточните у клиента и напишите в комментарии."
    return FactAnswer("ticket_address", answer, _source(f"Заявка №{ticket.id}"))


def _ticket_status(facts: Facts, text: str) -> FactAnswer | None:
    ticket = facts.target(text)
    if ticket is None or ticket.state is None:
        return None
    answer = f"Заявка {ticket_name(ticket)} сейчас: {state_name(ticket)}."
    review = ticket.completion_review
    if review and review.state == "rejected":
        answer = f"Диспетчер вернул заявку {ticket_name(ticket)} в работу"
        answer += f": {review.decision_comment}." if review.decision_comment else "."
    if ticket.state == "cancelled" and ticket.cancel_reason:
        answer = f"Заявка {ticket_name(ticket)} отменена: {ticket.cancel_reason}."
    return FactAnswer("ticket_status", answer, _source(f"Заявка №{ticket.id}"))


def author_label(comment: CommentContext) -> str:
    if comment.author is None:
        return "без автора"
    name = " ".join(part for part in (comment.author.name, comment.author.surname) if part)
    role = ROLE_LABELS.get(comment.author.role or "")
    return f"{name} ({role})" if role else name or "без автора"


def _ticket_notes(facts: Facts, text: str) -> FactAnswer | None:
    ticket = facts.target(text)
    if ticket is None:
        return None
    lines = []
    if ticket.description:
        lines.append(f"Описание: {ticket.description}")
    for comment in ticket.comments[-3:]:
        stamp = f"{when(comment.created_at, facts.today)}, " if comment.created_at else ""
        lines.append(f"• {stamp}{author_label(comment)}: {comment.text}")
    if lines:
        answer = f"По заявке {ticket_name(ticket)}:\n" + "\n".join(lines)
    elif ticket.comments_count:
        count = plural(ticket.comments_count, "комментарий", "комментария", "комментариев")
        answer = f"В заявке {ticket_name(ticket)} {count} — откройте её карточку, чтобы прочитать."
    else:
        answer = f"Описания и комментариев по заявке {ticket_name(ticket)} нет."
    return FactAnswer("ticket_notes", answer, _source(f"Заявка №{ticket.id}"))


def _ticket_equipment(facts: Facts, text: str) -> FactAnswer | None:
    ticket = facts.target(text)
    if ticket is None:
        return None
    items = ticket.appliances or ticket.required_appliances
    if not items:
        return None
    listed = "; ".join(f"{i.appliance_name} — {i.quantity} {i.unit or 'шт'}" for i in items)
    answer = f"По заявке {ticket_name(ticket)} нужно: {listed}."
    return FactAnswer("ticket_equipment", answer, _source(f"Заявка №{ticket.id}"))


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def change_phrase(change: TicketChange, today: date | None) -> str:
    fields = change.fields
    # Ticket fields, or visit fields as the day-plan diff names them.
    for key in ("planned_start_at", "service_start_at", "planned_arrival_at", "arrival_at"):
        field = fields.get(key)
        before = _as_datetime(field.previous) if field else None
        after = _as_datetime(field.current) if field else None
        if before and after:
            return f"перенесли с {when(before, today)} на {when(after, today)}"
    window = fields.get("visit_window_start")
    start = _as_datetime(window.current) if window else None
    if change.kind == "window_changed" and start:
        end = fields.get("visit_window_end")
        finish = _as_datetime(end.current) if end else None
        return f"изменили окно визита на {interval(start, finish, today)}"
    return {
        "unassigned": "сняли с вас",
        "reassigned": "передали другому исполнителю",
        "cancelled": "отменили",
        "redirected": "перенаправили",
        "delayed": "отметили задержку",
        "completion_rejected": "диспетчер вернул в работу",
        "reopened": "переоткрыли",
        "window_changed": "изменили окно визита",
        "rescheduled": "перенесли",
    }.get(change.kind, "изменили")


def _reason(text: str | None) -> str:
    if not text:
        return NO_REASON
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


def _removed_answer(removed: list[RemovedTicket], today: date | None) -> str:
    def line(item: RemovedTicket) -> str:
        stamp = f" {at_time(item.at, today)}" if item.at else ""
        name = f"№{item.ticket_id} «{item.title}»"
        return f"заявку {name} сняли с вас{stamp}: {_reason(item.reason_text)}"

    if len(removed) == 1:
        text = line(removed[0])
        return text[0].upper() + text[1:] + "."
    return "Сегодня с вас сняли заявки:\n" + "\n".join(f"• {line(item)}" for item in removed)


def _why_changed(facts: Facts, text: str) -> FactAnswer | None:
    removed = facts.day.removed_tickets if facts.day else []
    asks_removal = re.search(r"снял|сняли|забрал|убрал|отдал|передал|другому", text)
    if removed:
        number = re.search(r"(?:№|номер|заявк[а-я]*)\s*(\d{1,7})\b", text)
        wanted = int(number.group(1)) if number else None
        matching = [r for r in removed if wanted is None or r.ticket_id == wanted]
        if matching and (asks_removal or wanted is not None):
            return FactAnswer(
                "why_changed", _removed_answer(matching, facts.today), _source("Мой день")
            )
    ticket = facts.target(text)
    if ticket is None:
        return None
    history = ticket.changes or ([ticket.last_change] if ticket.last_change else [])
    relevant = [change for change in history if change.kind in CHANGE_KINDS]
    if not relevant:
        planned = interval(ticket.planned_start_at, ticket.planned_end_at, facts.today)
        answer = f"По заявке {ticket_name(ticket)} изменений не было"
        answer += f": она стоит на {planned}." if planned else "."
        return FactAnswer("why_changed", answer, _source(f"История заявки №{ticket.id}"))
    change = relevant[-1]
    reason = change.reason_text
    if change.kind == "cancelled" and ticket.cancel_reason:
        reason = ticket.cancel_reason
    answer = f"Заявку {ticket_name(ticket)} {change_phrase(change, facts.today)}"
    answer += f" (изменено {at_time(change.at, facts.today)}): {_reason(reason)}."
    if len(relevant) > 1:
        answer += f" Всего изменений: {len(relevant)}, это последнее."
    return FactAnswer("why_changed", answer, _source(f"История заявки №{ticket.id}"))


BUILDERS: dict[str, Callable[[Facts, str], FactAnswer | None]] = {
    "greeting": _greeting,
    "why_changed": _why_changed,
    "shift": _shift,
    "day_count": _day_count,
    "next_ticket": _next_ticket,
    "current_ticket": _current_ticket,
    "ticket_time": _ticket_time,
    "ticket_status": _ticket_status,
    "ticket_equipment": _ticket_equipment,
    "ticket_notes": _ticket_notes,
    "ticket_address": _ticket_address,
    "day_list": _day_list,
}


def answer_from_facts(request: ChatRequest) -> FactAnswer | None:
    intents = detect_intents(request.message)
    if not intents:
        return None
    facts = Facts(request)
    text = normalize(request.message)
    answers = [BUILDERS[intent](facts, text) for intent in intents]
    answers = [answer for answer in answers if answer is not None]
    if not answers:
        return None
    sources = list({s.section: s for a in answers for s in a.sources}.values())
    return FactAnswer(
        "+".join(a.intent for a in answers), " ".join(a.text for a in answers), sources
    )
