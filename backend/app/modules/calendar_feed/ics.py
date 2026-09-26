"""Render planned tickets as an iCalendar (RFC 5545) document without database access."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone

from icalendar import Calendar, Event

from app.modules.locations.schemas import LocationRead

MOSCOW = timezone(timedelta(hours=3))
# Calendar clients poll subscribed feeds; they may ignore the hint and use their own period.
REFRESH_INTERVAL = timedelta(minutes=15)
STATUS_LABELS = {
    "planned": "Запланирована",
    "in_progress": "В работе",
    "completed": "Завершена",
    "wont_fix": "Не будет исправлено",
}
CATEGORY_LABELS = {
    "emergency": "Авария",
    "connection": "Подключение",
    "repair": "Локальная работа",
    "additional": "Дозаказ",
}


def _location(ticket: Mapping) -> LocationRead:
    # The ticket row has its own id, so the location id arrives as location_id.
    fields = {key: ticket[key] for key in LocationRead.model_fields if key != "id"}
    return LocationRead(id=ticket["location_id"], **fields)


def _navigation_address(location: LocationRead) -> str:
    """City, street and house only: navigators do not understand entrances and flats."""
    parts = [location.city, location.street, f"д. {location.building_number}"]
    if location.block is not None:
        parts.append(location.block)
    return ", ".join(parts)


def _description(ticket: Mapping, location: LocationRead, ticket_url: str | None) -> str:
    window_start = ticket["visit_window_start"].astimezone(MOSCOW)
    window_end = ticket["visit_window_end"].astimezone(MOSCOW)
    lines = [
        f"Тип работ: {ticket['work_type']}",
        f"Категория: {CATEGORY_LABELS.get(ticket.get('category'), ticket.get('category', ''))}",
        f"Приоритет: {ticket.get('priority', '')}",
        f"Статус: {STATUS_LABELS.get(ticket['status'], ticket['status'])}",
        f"Адрес: {location.address}",
        f"Окно визита (МСК): {window_start:%d.%m %H:%M} – {window_end:%d.%m %H:%M}",
    ]
    if ticket.get("received_at"):
        received_at = ticket["received_at"].astimezone(MOSCOW)
        lines.append(f"Поступила: {received_at:%d.%m %H:%M} МСК")
    if ticket.get("sla_deadline_at"):
        sla_deadline_at = ticket["sla_deadline_at"].astimezone(MOSCOW)
        lines.append(f"Срок SLA: до {sla_deadline_at:%d.%m %H:%M} МСК")
    if ticket.get("required_transport_type"):
        lines.append(f"Требуемый транспорт: {ticket['required_transport_type']}")
    if ticket["description"]:
        lines += ["", ticket["description"]]
    if ticket_url:
        lines += ["", f"Карточка заявки: {ticket_url}"]
    return "\n".join(lines)


def _released_event(ticket: Mapping, stamp: datetime) -> Event:
    """Same UID as before, status CANCELLED, nothing about the client or the address."""
    event = Event()
    event.add("uid", f"ticket-{ticket['id']}@beeline-business")
    event.add("dtstamp", stamp)
    event.add("last-modified", ticket["updated_at"].astimezone(UTC))
    event.add("dtstart", ticket["planned_start_at"].astimezone(UTC))
    event.add("dtend", ticket["planned_end_at"].astimezone(UTC))
    event.add("summary", f"Заявка #{ticket['id']} снята с вас")
    event.add("status", "CANCELLED")
    return event


def build_calendar(
    owner_name: str,
    tickets: list[Mapping],
    *,
    frontend_url: str | None,
    now: datetime | None = None,
    released: list[Mapping] = (),
    truncated: bool = False,
) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", "-//Beeline Business//Field Service//RU")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", f"Заявки: {owner_name}")
    calendar.add("x-wr-timezone", "Europe/Moscow")
    calendar.add("refresh-interval", REFRESH_INTERVAL, parameters={"VALUE": "DURATION"})
    calendar.add("x-published-ttl", "PT15M")

    if truncated:
        calendar.add(
            "x-wr-caldesc",
            f"Показаны {len(tickets)} ближайших визитов: остальные не поместились в файл. "
            "Полный план — в приложении.",
        )
    stamp = (now or datetime.now(UTC)).astimezone(UTC)
    for ticket in released:
        calendar.add_component(_released_event(ticket, stamp))
    base_url = frontend_url.rstrip("/") if frontend_url else None
    for ticket in tickets:
        location = _location(ticket)
        ticket_url = f"{base_url}/tickets/{ticket['id']}" if base_url else None
        event = Event()
        # A stable UID lets the calendar update the event instead of duplicating it.
        event.add("uid", f"ticket-{ticket['id']}@beeline-business")
        event.add("dtstamp", stamp)
        event.add("last-modified", ticket["updated_at"].astimezone(UTC))
        event.add("dtstart", ticket["planned_start_at"].astimezone(UTC))
        event.add("dtend", ticket["planned_end_at"].astimezone(UTC))
        event.add("summary", f"Заявка #{ticket['id']}: {ticket['title']}")
        event.add("location", _navigation_address(location))
        if location.latitude is not None and location.longitude is not None:
            event.add("geo", (location.latitude, location.longitude))
        event.add("description", _description(ticket, location, ticket_url))
        if ticket_url:
            event.add("url", ticket_url)
        event.add("status", "CANCELLED" if ticket["status"] == "wont_fix" else "CONFIRMED")
        if ticket["status"] == "completed":
            # A done visit stays in the calendar as history; the mark makes it obvious.
            event["summary"] = f"✓ {event['summary']}"
        calendar.add_component(event)
    return calendar.to_ical()
