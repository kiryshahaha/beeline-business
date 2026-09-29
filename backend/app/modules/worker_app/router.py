"""Worker-only read model for the mobile home screen."""

import asyncio
from collections import defaultdict, deque
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from time import monotonic, perf_counter
from typing import Annotated
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import oplog
from app.core.config import get_settings
from app.db.session import get_session
from app.modules.appliances import service as appliances_service
from app.modules.auth.dependencies import get_current_user
from app.modules.comments import repository as comments_repository
from app.modules.comments import service as comments_service
from app.modules.comments.service import _comment_from_row
from app.modules.execution import repository as execution_repository
from app.modules.execution import service as execution_service
from app.modules.execution.enums import WorkEventType
from app.modules.execution.schemas import ExecutionCommand
from app.modules.notifications.enums import NotificationKind
from app.modules.service_areas.territory import resolve_worker
from app.modules.tickets import repository as tickets_repository
from app.modules.tickets import service as ticket_service
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead
from app.modules.users.service import get_worker_day_shift
from app.modules.worker_app.schemas import (
    AssistantChatRequest,
    CompletionDecision,
    TicketProblemRequest,
)

MOSCOW = ZoneInfo("Europe/Moscow")
router = APIRouter(prefix="/api/v1", tags=["worker app"])
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[UserRead, Depends(get_current_user)]
_assistant_lock = asyncio.Lock()
_assistant_requests: dict[int, deque[float]] = defaultdict(deque)


def _worker_required(user: UserRead) -> None:
    if user.role != UserRole.WORKER:
        raise HTTPException(status_code=403, detail="Ручка доступна только исполнителю")


@router.get("/me/day")
def get_my_day(
    session: DatabaseSession,
    user: CurrentUser,
    target_date: Annotated[date | None, Query(alias="date")] = None,
) -> dict:
    _worker_required(user)
    target_date = target_date or datetime.now(MOSCOW).date()
    area_id = resolve_worker(session, user.id)
    shift = get_worker_day_shift(session, user.id, target_date)
    day_state = (
        session.execute(
            text("""
            SELECT available, unavailable_until, reason, current_ticket_id,
                   en_route_started_at, expected_available_at
            FROM worker_day_states
            WHERE worker_id = :worker_id AND service_area_id = :area_id
              AND route_date = :route_date
        """),
            {"worker_id": user.id, "area_id": area_id, "route_date": target_date},
        )
        .mappings()
        .one_or_none()
    )
    revision_row = (
        session.execute(
            text("""
            SELECT revision, reason, effective_at, plan_state
            FROM day_plan_revisions
            WHERE service_area_id = :area_id AND route_date = :route_date AND is_current
        """),
            {"area_id": area_id, "route_date": target_date},
        )
        .mappings()
        .one_or_none()
    )
    plan_state = (revision_row or {}).get("plan_state") or {}
    visits = [item for item in plan_state.get("visits", []) if item.get("worker_id") == user.id]
    visits.sort(
        key=lambda item: (item.get("sequence") or 2_147_483_647, item.get("ticket_id") or 0)
    )
    visit_by_ticket = {item["ticket_id"]: item for item in visits}
    ids = list(
        session.execute(
            text("""
            SELECT DISTINCT ticket.id
            FROM tickets AS ticket
            WHERE ticket.assigned_worker_id = :worker_id
              AND (
                (ticket.planned_start_at IS NOT NULL AND
                 (ticket.planned_start_at AT TIME ZONE 'Europe/Moscow')::date = :route_date)
                OR ticket.lifecycle_state IN ('en_route', 'in_progress')
                OR (ticket.lifecycle_state IN ('completed', 'cancelled') AND EXISTS (
                    SELECT 1 FROM work_events AS event
                    WHERE event.ticket_id = ticket.id AND event.route_date = :route_date
                      AND event.event_type IN ('complete', 'cancel_ticket')
                ))
              )
            ORDER BY ticket.id
        """),
            {"worker_id": user.id, "route_date": target_date},
        ).scalars()
    )
    tickets = []
    for ticket_id in ids:
        item = ticket_service.get_ticket(session, ticket_id, user).model_dump(mode="json")
        visit = visit_by_ticket.get(ticket_id, {})
        review = (
            session.execute(
                text("""
                SELECT id, state, note, actual_duration_minutes
                FROM ticket_completion_reviews
                WHERE ticket_id = :ticket_id
                ORDER BY execution_cycle DESC LIMIT 1
            """),
                {"ticket_id": ticket_id},
            )
            .mappings()
            .one_or_none()
        )
        item.update(
            sequence=visit.get("sequence"),
            planned_arrival_at=visit.get("arrival_at"),
            required_appliances=[
                dict(row)
                for row in session.execute(
                    text("""
                        SELECT ta.appliance_id, appliance.name AS appliance_name,
                               appliance.unit, ta.quantity
                        FROM ticket_appliances ta
                        JOIN appliances appliance ON appliance.id=ta.appliance_id
                        WHERE ta.ticket_id=:ticket_id ORDER BY ta.appliance_id
                    """),
                    {"ticket_id": ticket_id},
                )
                .mappings()
                .all()
            ],
            comments_count=session.execute(
                text("SELECT count(*) FROM ticket_comments WHERE ticket_id = :ticket_id"),
                {"ticket_id": ticket_id},
            ).scalar_one(),
            completion_review=(dict(review) if review else None),
            last_change=None,
        )
        history = get_ticket_changes(ticket_id, session, user, target_date=target_date, limit=1)
        item["last_change"] = history["changes"][-1] if history["changes"] else None
        tickets.append(item)
    tickets.sort(
        key=lambda item: (
            item["sequence"] if item["sequence"] is not None else 2_147_483_647,
            item.get("planned_start_at") or "",
            item["id"],
        )
    )
    states = [ticket.get("state") for ticket in tickets]
    current_id = (day_state or {}).get("current_ticket_id")
    if current_id is None:
        current = next(
            (ticket for ticket in tickets if ticket.get("state") in {"en_route", "in_progress"}),
            None,
        )
        current_id = current["id"] if current else None
    next_ticket = next(
        (
            ticket
            for ticket in tickets
            if ticket["id"] != current_id and ticket.get("state") in {"assigned", "dispatched"}
        ),
        None,
    )
    removed = (
        session.execute(
            text("""
            SELECT event.ticket_id, ticket.title, event.occurred_at, event.source
            FROM ticket_assignment_events AS event
            JOIN tickets AS ticket ON ticket.id = event.ticket_id
            WHERE event.previous_worker_id = :worker_id
              AND event.new_worker_id IS DISTINCT FROM :worker_id
              AND (event.occurred_at AT TIME ZONE 'Europe/Moscow')::date = :route_date
            ORDER BY event.occurred_at, event.id
        """),
            {"worker_id": user.id, "route_date": target_date},
        )
        .mappings()
        .all()
    )
    exception = session.execute(
        text(
            "SELECT is_working FROM worker_shift_exceptions "
            "WHERE worker_id=:worker_id AND exception_date=:route_date"
        ),
        {"worker_id": user.id, "route_date": target_date},
    ).scalar_one_or_none()
    office = (
        session.execute(
            text("""
            SELECT office.id, office.name,
                   concat_ws(', ', city.name, street.name, 'д. ' || building.number,
                             NULLIF(building.block, '')) AS address
            FROM workers worker
            LEFT JOIN offices office ON office.id = worker.stock_office_id
            LEFT JOIN locations location ON location.id = office.location_id
            LEFT JOIN buildings building ON building.id = location.building_id
            LEFT JOIN streets street ON street.id = building.street_id
            LEFT JOIN cities city ON city.id = street.city_id
            WHERE worker.user_id = :worker_id
        """),
            {"worker_id": user.id},
        )
        .mappings()
        .one_or_none()
    )
    area_name = session.execute(
        text("SELECT name FROM service_areas WHERE id=:area_id"), {"area_id": area_id}
    ).scalar_one()
    removed_tickets = []
    for row in removed:
        history = get_ticket_changes(
            row["ticket_id"], session, user, target_date=target_date, limit=100
        )["changes"]
        reason = next(
            (
                item
                for item in reversed(history)
                if item["kind"] in {"unassigned", "reassigned"} and item["at"] == row["occurred_at"]
            ),
            None,
        )
        removed_tickets.append(
            {
                "ticket_id": row["ticket_id"],
                "title": row["title"],
                "at": row["occurred_at"],
                "reason_code": reason["reason_code"] if reason else "unknown",
                "reason_text": reason["reason_text"] if reason else None,
            }
        )
    start = shift.start if shift else None
    end = shift.end if shift else None
    completed = sum(state == "completed" for state in states)
    awaiting = sum(
        (ticket.get("completion_review") or {}).get("state") == "pending" for ticket in tickets
    )
    return {
        "date": target_date.isoformat(),
        "worker": {
            "id": user.id,
            "name": user.name,
            "surname": user.surname,
            "transport_type": user.worker_profile.transport_type.value,
            "skills": user.worker_profile.skills,
            "brigade": {"id": user.brigade_id, "name": user.brigade_name}
            if user.brigade_id
            else None,
            "service_area": {"id": area_id, "name": area_name},
            "office": dict(office) if office and office["id"] else None,
        },
        "shift": {
            "is_working_day": shift is not None,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "exception": {"is_working": exception} if exception is not None else None,
        },
        "day_state": {
            "available": (day_state or {}).get("available", True),
            "unavailable_until": (day_state or {}).get("unavailable_until"),
            "reason": (day_state or {}).get("reason"),
            "current_ticket_id": (day_state or {}).get("current_ticket_id"),
            "en_route_started_at": (day_state or {}).get("en_route_started_at"),
            "expected_available_at": (day_state or {}).get("expected_available_at"),
        },
        "plan": (
            {
                "revision": revision_row["revision"],
                "reason": revision_row["reason"],
                "effective_at": revision_row["effective_at"],
            }
            if revision_row
            else None
        ),
        "summary": {
            "total": len(tickets),
            "completed": completed,
            "awaiting_confirmation": awaiting,
            "in_progress": sum(state == "in_progress" for state in states),
            "remaining": sum(state in {"assigned", "dispatched", "en_route"} for state in states),
            "cancelled": sum(state == "cancelled" for state in states),
        },
        "current_ticket_id": current_id,
        "next_ticket_id": next_ticket["id"] if next_ticket else None,
        "tickets": tickets,
        "removed_tickets": removed_tickets,
    }


@router.post("/tickets/{ticket_id}/problem", status_code=201)
def report_ticket_problem(
    ticket_id: int,
    data: TicketProblemRequest,
    session: DatabaseSession,
    user: CurrentUser,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    _worker_required(user)
    if not idempotency_key or not idempotency_key.strip() or len(idempotency_key) > 128:
        raise HTTPException(status_code=422, detail="Требуется Idempotency-Key")
    key = idempotency_key.strip()
    reason = f"Проблема: {data.type}. {data.text}"
    context = session.begin() if not session.in_transaction() else nullcontext()
    with context:
        row = (
            session.execute(
                text("""
                SELECT ticket.revision, ticket.lifecycle_state, ticket.service_area_id
                FROM tickets AS ticket
                WHERE ticket.id=:ticket_id AND ticket.assigned_worker_id=:worker_id
                FOR UPDATE
            """),
                {"ticket_id": ticket_id, "worker_id": user.id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if row["revision"] != data.expected_revision:
            raise HTTPException(
                status_code=409,
                detail={"code": "revision_conflict", "current_revision": row["revision"]},
            )
        existing = execution_repository.find_event_by_key(session, key)
        if existing:
            if (
                existing["ticket_id"] != ticket_id
                or existing["event_type"] != WorkEventType.PROBLEM_REPORTED.value
            ):
                raise HTTPException(status_code=409, detail={"code": "idempotency_conflict"})
            comment_id = existing["payload"].get("comment_id")
            if comment_id is None:
                raise HTTPException(status_code=409, detail={"code": "idempotency_conflict"})
            return {
                "comment": _comment_from_row(comments_repository.find_comment(session, comment_id)),
                "notified_observers": 0,
            }
        comment_id = comments_repository.add_comment(session, ticket_id, user.id, reason)
        now = datetime.now(UTC)
        event_id = execution_repository.insert_work_event(
            session,
            event_type=WorkEventType.PROBLEM_REPORTED.value,
            ticket_id=ticket_id,
            worker_id=user.id,
            service_area_id=resolve_worker(session, user.id),
            route_date=now.astimezone(MOSCOW).date(),
            occurred_at=now,
            actor_id=user.id,
            reason=None,
            previous_state=row["lifecycle_state"],
            new_state=row["lifecycle_state"],
            before_revision=row["revision"],
            after_revision=row["revision"],
            idempotency_key=key,
            payload={
                "problem_type": data.type,
                "comment_id": comment_id,
                "expected_available_at": data.expected_available_at.isoformat()
                if data.expected_available_at
                else None,
            },
        )
        if event_id is None:
            raise HTTPException(status_code=409, detail={"code": "idempotency_conflict"})
        recipients = tickets_repository.list_observer_ids(session)
        worker = (
            session.execute(
                text("SELECT id, name, surname FROM users WHERE id=:id"), {"id": user.id}
            )
            .mappings()
            .one()
        )
        tickets_repository.add_notification_events(
            session,
            recipients,
            kind=NotificationKind.TICKET_PROBLEM_REPORTED,
            ticket_id=ticket_id,
            data={
                "worker_id": user.id,
                "worker": dict(worker),
                "type": data.type,
                "text": data.text,
                "expected_available_at": data.expected_available_at.isoformat()
                if data.expected_available_at
                else None,
            },
        )
        comment = _comment_from_row(comments_repository.find_comment(session, comment_id))
    return {"comment": comment, "notified_observers": len(recipients)}


@router.get("/tickets/completion-reviews")
def list_completion_reviews(
    session: DatabaseSession,
    user: CurrentUser,
    state: str = Query(default="pending", pattern="^(pending|confirmed|rejected|all)$"),
    service_area_id: int | None = Query(default=None, ge=1),
    target_date: date | None = Query(default=None, alias="date"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    if user.role not in {UserRole.OBSERVER, UserRole.FOREMAN}:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    filters = ["(:state = 'all' OR review.state = :state)"]
    params: dict[str, object] = {"state": state, "limit": limit, "offset": offset}
    if service_area_id is not None:
        filters.append("COALESCE(ticket.service_area_id, building.service_area_id) = :area_id")
        params["area_id"] = service_area_id
    if target_date is not None:
        filters.append("(review.requested_at AT TIME ZONE 'Europe/Moscow')::date = :target_date")
        params["target_date"] = target_date
    if user.role == UserRole.FOREMAN:
        filters.append(
            "EXISTS (SELECT 1 FROM brigades brigade "
            "WHERE brigade.foreman_id=:foreman_id AND brigade.id=ticket.brigade_id)"
        )
        params["foreman_id"] = user.id
    rows = (
        session.execute(
            text(
                """
            SELECT review.id, review.ticket_id, ticket.title, ticket.category,
                   review.requested_by, worker.name AS worker_name,
                   worker.surname AS worker_surname, review.requested_at,
                   review.note, review.actual_duration_minutes, review.state,
                   city.name AS city_name, street.name AS street_name,
                   building.number AS building_number
            FROM ticket_completion_reviews review
            JOIN tickets ticket ON ticket.id=review.ticket_id
            JOIN users worker ON worker.id=review.requested_by
            JOIN locations location ON location.id=ticket.location_id
            JOIN buildings building ON building.id=location.building_id
            JOIN streets street ON street.id=building.street_id
            JOIN cities city ON city.id=street.city_id
            WHERE """
                + " AND ".join(filters)
                + " ORDER BY review.requested_at DESC, review.id DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        .mappings()
        .all()
    )
    return [
        {
            "review_id": row["id"],
            "ticket": {
                "id": row["ticket_id"],
                "title": row["title"],
                "category": row["category"],
                "address": f"{row['city_name']}, {row['street_name']}, д. {row['building_number']}",
            },
            "worker": {
                "id": row["requested_by"],
                "name": row["worker_name"],
                "surname": row["worker_surname"],
            },
            "requested_at": row["requested_at"],
            "note": row["note"],
            "actual_duration_minutes": row["actual_duration_minutes"],
            "state": row["state"],
        }
        for row in rows
    ]


@router.post("/tickets/{ticket_id}/completion/confirm")
def confirm_completion(
    ticket_id: int,
    data: CompletionDecision,
    session: DatabaseSession,
    user: CurrentUser,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    if user.role != UserRole.OBSERVER:
        raise HTTPException(status_code=403, detail="Подтвердить завершение может диспетчер")
    return _decide_completion(ticket_id, data, session, user, idempotency_key, reject=False)


@router.post("/tickets/{ticket_id}/completion/reject")
def reject_completion(
    ticket_id: int,
    data: CompletionDecision,
    session: DatabaseSession,
    user: CurrentUser,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    if user.role != UserRole.OBSERVER:
        raise HTTPException(status_code=403, detail="Отклонить завершение может диспетчер")
    if not data.reason or not data.reason.strip():
        raise HTTPException(status_code=422, detail="Для отказа требуется reason")
    return _decide_completion(ticket_id, data, session, user, idempotency_key, reject=True)


def _decide_completion(ticket_id, data, session, user, idempotency_key, *, reject: bool):
    if not idempotency_key or not idempotency_key.strip() or len(idempotency_key) > 128:
        raise HTTPException(status_code=422, detail="Требуется Idempotency-Key")
    key = idempotency_key.strip()
    context = session.begin() if not session.in_transaction() else nullcontext()
    with context:
        review = (
            session.execute(
                text("""
                SELECT id, requested_by, state, decision_idempotency_key
                FROM ticket_completion_reviews
                WHERE ticket_id=:ticket_id ORDER BY execution_cycle DESC LIMIT 1 FOR UPDATE
            """),
                {"ticket_id": ticket_id},
            )
            .mappings()
            .one_or_none()
        )
        if review is None:
            raise HTTPException(status_code=404, detail="Проверка завершения не найдена")
        expected_state = "rejected" if reject else "confirmed"
        if review["state"] != "pending":
            if review["state"] == expected_state and review["decision_idempotency_key"] == key:
                return {"ticket_id": ticket_id, "state": expected_state}
            raise HTTPException(status_code=409, detail={"code": "review_already_decided"})
        key_owner = session.execute(
            text(
                "SELECT id FROM ticket_completion_reviews "
                "WHERE decision_idempotency_key=:key AND id<>:review_id"
            ),
            {"key": key, "review_id": review["id"]},
        ).scalar_one_or_none()
        if key_owner is not None:
            raise HTTPException(status_code=409, detail={"code": "idempotency_conflict"})
        ticket = session.execute(
            text("SELECT revision FROM tickets WHERE id=:id FOR UPDATE"), {"id": ticket_id}
        ).scalar_one_or_none()
        if ticket is None:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if ticket != data.expected_revision:
            raise HTTPException(
                status_code=409, detail={"code": "revision_conflict", "current_revision": ticket}
            )
        reason = (data.reason or "").strip() if reject else None
        if reject:
            try:
                execution_service.reopen_ticket(
                    session,
                    ticket_id,
                    ExecutionCommand(
                        expected_revision=ticket, occurred_at=datetime.now(UTC), reason=reason
                    ),
                    actor_id=user.id,
                    idempotency_key=idempotency_key.strip(),
                )
            except Exception as error:
                raise HTTPException(
                    status_code=409, detail={"code": getattr(error, "code", "invalid_transition")}
                ) from error
        session.execute(
            text("""
                UPDATE ticket_completion_reviews
                SET state=:state, decided_by=:actor_id, decided_at=clock_timestamp(),
                    decision_comment=:comment, decision_idempotency_key=:key
                WHERE id=:review_id AND state='pending'
            """),
            {
                "state": "rejected" if reject else "confirmed",
                "actor_id": user.id,
                "comment": reason if reject else data.comment,
                "review_id": review["id"],
                "key": key,
            },
        )
        tickets_repository.add_notification_events(
            session,
            [review["requested_by"]],
            kind=NotificationKind.TICKET_COMPLETION_REJECTED
            if reject
            else NotificationKind.TICKET_COMPLETION_CONFIRMED,
            ticket_id=ticket_id,
            data={"reason": reason} if reject else {},
        )
    return {"ticket_id": ticket_id, "state": "rejected" if reject else "confirmed"}


@router.get("/tickets/{ticket_id}/changes")
def get_ticket_changes(
    ticket_id: int,
    session: DatabaseSession,
    user: CurrentUser,
    target_date: date | None = Query(default=None, alias="date"),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict:
    if user.role == UserRole.WORKER:
        assignment_rows = (
            session.execute(
                text("""
                SELECT previous_worker_id, new_worker_id, actor_id, source, occurred_at
                FROM ticket_assignment_events WHERE ticket_id=:ticket_id ORDER BY occurred_at, id
            """),
                {"ticket_id": ticket_id},
            )
            .mappings()
            .all()
        )
        currently_assigned = session.execute(
            text("SELECT assigned_worker_id=:worker_id FROM tickets WHERE id=:id"),
            {"id": ticket_id, "worker_id": user.id},
        ).scalar_one_or_none()
        if currently_assigned is not True and not any(
            row["previous_worker_id"] == user.id or row["new_worker_id"] == user.id
            for row in assignment_rows
        ):
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        ticket_service.get_ticket_unscoped(session, ticket_id)
    else:
        try:
            ticket_service.get_ticket(session, ticket_id, user)
        except ticket_service.TicketNotFoundError as error:
            raise HTTPException(status_code=404, detail="Заявка не найдена") from error
        assignment_rows = (
            session.execute(
                text("""
                SELECT previous_worker_id, new_worker_id, actor_id, source, occurred_at
                FROM ticket_assignment_events WHERE ticket_id=:ticket_id ORDER BY occurred_at, id
            """),
                {"ticket_id": ticket_id},
            )
            .mappings()
            .all()
        )
    cutoff = None
    changes: list[dict] = []
    for row in assignment_rows:
        if user.role == UserRole.WORKER:
            if row["previous_worker_id"] == user.id and row["new_worker_id"] != user.id:
                cutoff = row["occurred_at"]
            elif row["previous_worker_id"] != user.id and row["new_worker_id"] != user.id:
                continue
        kind = (
            "assigned"
            if row["previous_worker_id"] is None
            else ("unassigned" if row["new_worker_id"] is None else "reassigned")
        )
        fields = {"worker_id": {"from": row["previous_worker_id"], "to": row["new_worker_id"]}}
        if (
            user.role == UserRole.WORKER
            and row["previous_worker_id"] == user.id
            and row["new_worker_id"] != user.id
        ):
            fields["worker_id"]["to"] = None
        actor = (
            session.execute(
                text("SELECT id, name, surname, role FROM users WHERE id=:id"),
                {"id": row["actor_id"]},
            )
            .mappings()
            .one_or_none()
            if row["actor_id"]
            else None
        )
        changes.append(
            {
                "at": row["occurred_at"],
                "kind": kind,
                "source": "planner" if row["source"] == "plan" else "dispatcher",
                "actor": (
                    {
                        "id": actor["id"],
                        "name": f"{actor['name']} {actor['surname']}",
                        "role": actor["role"],
                    }
                    if actor
                    else None
                ),
                "fields": fields,
                "reason_code": "line_status" if row["source"] == "line_status" else "unknown",
                "reason_text": "Исполнитель снят с линии"
                if row["source"] == "line_status"
                else None,
                "related_ticket_id": None,
            }
        )
        if cutoff is not None:
            break
    event_rows = (
        session.execute(
            text("""
            SELECT event.occurred_at, event.event_type, event.reason, event.payload,
                   event.actor_id, event.before_revision, event.after_revision
            FROM work_events event WHERE event.ticket_id=:ticket_id
            ORDER BY event.occurred_at, event.id
        """),
            {"ticket_id": ticket_id},
        )
        .mappings()
        .all()
    )
    for row in event_rows:
        if cutoff is not None and row["occurred_at"] > cutoff:
            continue
        kind = {
            "progress_delay": "delayed",
            "window_change": "window_changed",
            "redirect": "redirected",
            "cancel_ticket": "cancelled",
            "reopen": "reopened",
            "complete": "completed",
            "problem_reported": "problem_reported",
        }.get(row["event_type"])
        if not kind:
            continue
        changes.append(
            {
                "at": row["occurred_at"],
                "kind": kind,
                "source": "worker"
                if row["event_type"] in {"progress_delay", "problem_reported"}
                else "dispatcher",
                "actor": None,
                "fields": {},
                "reason_code": row["event_type"],
                "reason_text": row["reason"],
                "related_ticket_id": (row["payload"] or {}).get("ticket_id"),
            }
        )
    review_rows = (
        session.execute(
            text("""
            SELECT requested_at, state, decided_at, decision_comment, requested_by
            FROM ticket_completion_reviews
            WHERE ticket_id=:ticket_id
            ORDER BY requested_at, id
        """),
            {"ticket_id": ticket_id},
        )
        .mappings()
        .all()
    )
    for row in review_rows:
        if cutoff is not None and row["requested_at"] > cutoff:
            continue
        if row["state"] in {"confirmed", "rejected"} and row["decided_at"] is not None:
            changes.append(
                {
                    "at": row["decided_at"],
                    "kind": "completion_confirmed"
                    if row["state"] == "confirmed"
                    else "completion_rejected",
                    "source": "dispatcher",
                    "actor": None,
                    "fields": {},
                    "reason_code": row["state"],
                    "reason_text": row["decision_comment"],
                    "related_ticket_id": None,
                }
            )
    revision_rows = (
        session.execute(
            text("""
            SELECT revision_row.effective_at, revision_row.reason, revision_row.event_id,
                   revision_row.diff, event.event_type, event.reason AS event_reason,
                   event.payload AS event_payload
            FROM day_plan_revisions revision_row
            LEFT JOIN work_events event ON event.id=revision_row.event_id
            WHERE revision_row.diff @> jsonb_build_object(
                    'changed', jsonb_build_array(jsonb_build_object('ticket_id', :ticket_id)))
               OR revision_row.diff @> jsonb_build_object(
                    'added', jsonb_build_array(jsonb_build_object('ticket_id', :ticket_id)))
               OR revision_row.diff @> jsonb_build_object(
                    'removed', jsonb_build_array(jsonb_build_object('ticket_id', :ticket_id)))
            ORDER BY revision_row.effective_at, revision_row.revision
        """),
            {"ticket_id": ticket_id},
        )
        .mappings()
        .all()
    )
    for row in revision_rows:
        if cutoff is not None and row["effective_at"] > cutoff:
            continue
        diff = row["diff"] or {}
        changed = next(
            (item for item in diff.get("changed", []) if item.get("ticket_id") == ticket_id), None
        )
        added = next(
            (item for item in diff.get("added", []) if item.get("ticket_id") == ticket_id), None
        )
        removed_entry = next(
            (item for item in diff.get("removed", []) if item.get("ticket_id") == ticket_id), None
        )
        if changed:
            kind, fields = "rescheduled", changed.get("changes", {})
        elif added:
            kind = "assigned"
            fields = {"worker_id": {"from": None, "to": added.get("worker_id")}}
        elif removed_entry:
            kind = "unassigned"
            fields = {"worker_id": {"from": removed_entry.get("worker_id"), "to": None}}
        else:
            continue
        reason_code, reason_text = "unknown", None
        related_ticket_id = None
        if row["event_type"] == "worker_unavailable":
            reason_code = (
                "worker_unavailable_self"
                if (row["event_payload"] or {}).get("worker_id") == user.id
                else "worker_unavailable_other"
            )
            reason_text = row["event_reason"]
        elif row["reason"] == "manual_edit":
            reason_code, reason_text = "manual_edit", "Изменено диспетчером"
        elif row["reason"] == "event_replan":
            reason_code, reason_text = "previous_delay", row["event_reason"]
        changes.append(
            {
                "at": row["effective_at"],
                "kind": kind,
                "source": "dispatcher" if row["reason"] == "manual_edit" else "planner",
                "actor": None,
                "fields": fields,
                "reason_code": reason_code,
                "reason_text": reason_text,
                "related_ticket_id": related_ticket_id,
            }
        )
    if target_date is not None:
        changes = [
            change for change in changes if change["at"].astimezone(MOSCOW).date() == target_date
        ]
    changes.sort(key=lambda item: item["at"])
    changes = changes[-limit:]
    return {"ticket_id": ticket_id, "changes": changes}


@router.post("/assistant/chat")
async def assistant_chat(
    data: AssistantChatRequest,
    session: DatabaseSession,
    user: CurrentUser,
) -> dict:
    """Proxy a bounded chat request with only role-visible application context."""
    started = perf_counter()
    now = monotonic()
    async with _assistant_lock:
        requests = _assistant_requests[user.id]
        while requests and now - requests[0] >= 60:
            requests.popleft()
        if len(requests) >= 10:
            oplog.log(
                "assistant_chat",
                user_id=user.id,
                role=user.role.value,
                status_code=429,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise HTTPException(status_code=429, detail="Слишком много запросов к помощнику")
        requests.append(now)

    settings = get_settings()
    if not settings.assistant_enabled:
        oplog.log(
            "assistant_chat",
            user_id=user.id,
            role=user.role.value,
            status_code=503,
            duration_ms=(perf_counter() - started) * 1000,
        )
        raise HTTPException(status_code=503, detail="Помощник временно недоступен")

    context: dict = {}
    if user.role == UserRole.WORKER:
        today = datetime.now(MOSCOW).date()
        context["day"] = jsonable_encoder(get_my_day(session, user, today))
        context["tomorrow_shift"] = jsonable_encoder(
            get_my_day(session, user, today + timedelta(days=1))["shift"]
        )

    if data.ticket_id is not None:
        try:
            ticket = ticket_service.get_ticket(session, data.ticket_id, user)
        except ticket_service.TicketNotFoundError as error:
            raise HTTPException(status_code=404, detail="Заявка не найдена") from error
        ticket_context = ticket.model_dump(mode="json")
        if user.role == UserRole.WORKER:
            try:
                ticket_context.update(
                    comments=[
                        item.model_dump(mode="json")
                        for item in comments_service.list_comments(session, data.ticket_id, user)[
                            -10:
                        ]
                    ],
                    appliances=[
                        item.model_dump(mode="json")
                        for item in appliances_service.list_ticket_appliances(
                            session, data.ticket_id, user
                        )
                    ],
                    changes=jsonable_encoder(
                        get_ticket_changes(
                            data.ticket_id, session, user, target_date=None, limit=50
                        )
                    )["changes"],
                )
            except HTTPException:
                raise
            except Exception as error:
                # Context lookups stay inside the same role-scoped ticket access.
                oplog.log(
                    "assistant_chat_context_error",
                    user_id=user.id,
                    role=user.role.value,
                    ticket_id=data.ticket_id,
                    error=type(error).__name__.lower(),
                )
                raise HTTPException(
                    status_code=503, detail="Не удалось подготовить контекст"
                ) from error
        context["ticket"] = ticket_context

    payload = {
        "role": user.role.value,
        "message": data.message,
        "history": [item.model_dump(mode="json") for item in data.history],
        "context": context,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.assistant_timeout_seconds) as client:
            response = await client.post(f"{settings.assistant_url}/api/v1/chat", json=payload)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Assistant response must be a JSON object")
    except (httpx.HTTPError, ValueError) as error:
        oplog.log(
            "assistant_chat",
            user_id=user.id,
            role=user.role.value,
            ticket_id=data.ticket_id,
            status_code=getattr(getattr(error, "response", None), "status_code", 503),
            duration_ms=(perf_counter() - started) * 1000,
        )
        raise HTTPException(status_code=503, detail="Помощник временно недоступен") from error

    oplog.log(
        "assistant_chat",
        user_id=user.id,
        role=user.role.value,
        ticket_id=data.ticket_id,
        source_type=result.get("source_type"),
        status_code=200,
        duration_ms=(perf_counter() - started) * 1000,
    )
    return result
