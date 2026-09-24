"""Equipment as a physical resource: units go office -> engineer -> client, every move journaled.

Office stock counts units in the warehouse. A ticket allocation reserves units in its office
until they are issued; from then on they are on the engineer's hands and committed to the
ticket until written off at completion. A ticket_appliance_states row records that an
allocation left the office reservation (holder) or was written off (consumed_operation_id).
Callers hold the planning advisory lock, so balance checks and updates are serialized.
"""

from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.modules.appliances import repository
from app.modules.appliances.enums import ApplianceType
from app.modules.appliances.models import (
    Appliance,
    ApplianceMovement,
    ApplianceOperation,
    ApplianceStock,
    OfficeKitReserve,
    TicketAppliance,
    TicketApplianceState,
    WorkerAppliance,
)
from app.modules.offices.models import Office
from app.modules.tickets.models import Ticket

MOSCOW = ZoneInfo("Europe/Moscow")
TICKET_DAY = (
    "(COALESCE(t.planned_start_at, t.visit_window_start) AT TIME ZONE 'Europe/Moscow')::date"
)


class InventoryError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, **details):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details

    def detail(self) -> dict:
        return {"code": self.code, "message": self.message, **self.details}


def today() -> date:
    return datetime.now(MOSCOW).date()


def name(session: Session, appliance_id: int) -> str:
    appliance = session.get(Appliance, appliance_id)
    return appliance.name if appliance else f"№{appliance_id}"


def find_worker(session: Session, worker_id: int) -> dict:
    row = (
        session.execute(
            text("""
                SELECT w.user_id, w.workshift_start, w.workshift_end, b.office_id
                FROM workers w
                LEFT JOIN brigade_members bm ON bm.worker_id = w.user_id
                LEFT JOIN brigades b ON b.id = bm.brigade_id
                WHERE w.user_id = :id
            """),
            {"id": worker_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise InventoryError("worker_not_found", f"Инженер №{worker_id} не найден", 404)
    return dict(row)


def is_foreman_of(session: Session, foreman_id: int, worker_id: int) -> bool:
    return session.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM brigade_members bm JOIN brigades b ON b.id = bm.brigade_id
                WHERE bm.worker_id = :worker AND b.foreman_id = :foreman
            )
        """),
        {"worker": worker_id, "foreman": foreman_id},
    ).scalar_one()


def on_hand(session: Session, worker_id: int) -> dict[int, int]:
    rows = session.scalars(select(WorkerAppliance).where(WorkerAppliance.worker_id == worker_id))
    return {row.appliance_id: row.quantity for row in rows}


def committed(session: Session, worker_id: int) -> dict[int, int]:
    """Units on hand that belong to open tickets and are not written off yet."""
    rows = session.execute(
        text("""
            SELECT ta.appliance_id, SUM(ta.quantity) AS quantity
            FROM ticket_appliance_states s
            JOIN ticket_appliances ta
              ON ta.ticket_id = s.ticket_id AND ta.appliance_id = s.appliance_id
            JOIN tickets t ON t.id = s.ticket_id
            WHERE s.holder_worker_id = :worker AND s.consumed_operation_id IS NULL
              AND t.status IN ('planned', 'in_progress')
            GROUP BY ta.appliance_id
        """),
        {"worker": worker_id},
    )
    return {row.appliance_id: int(row.quantity) for row in rows}


def free_units(session: Session, worker_id: int) -> dict[int, int]:
    held, used = on_hand(session, worker_id), committed(session, worker_id)
    return {a: max(held.get(a, 0) - used.get(a, 0), 0) for a in held.keys() | used.keys()}


def change_on_hand(session: Session, worker_id: int, appliance_id: int, delta: int) -> None:
    row = session.get(WorkerAppliance, (worker_id, appliance_id), with_for_update=True)
    current = row.quantity if row else 0
    if current + delta < 0:
        raise InventoryError(
            "inventory_inconsistent",
            f"У инженера №{worker_id} числится {current} «{name(session, appliance_id)}»,"
            f" а требуется {-delta}",
            worker_id=worker_id,
            appliance_id=appliance_id,
            on_hand=current,
            required=-delta,
        )
    if row is None:
        session.add(WorkerAppliance(worker_id=worker_id, appliance_id=appliance_id, quantity=delta))
    elif current + delta == 0:
        session.delete(row)
    else:
        row.quantity = current + delta
    session.flush()


def change_stock(session: Session, office_id: int, appliance_id: int, delta: int) -> None:
    row = session.get(ApplianceStock, (office_id, appliance_id), with_for_update=True)
    current = row.stock if row else 0
    if current + delta < 0:
        raise InventoryError(
            "inventory_inconsistent",
            f"На складе офиса №{office_id} числится {current} «{name(session, appliance_id)}»,"
            f" а требуется {-delta}",
            office_id=office_id,
            appliance_id=appliance_id,
            stock=current,
            required=-delta,
        )
    if row is None:
        session.add(ApplianceStock(office_id=office_id, appliance_id=appliance_id, stock=delta))
    else:
        row.stock = current + delta
    session.flush()


def receipt(session: Session, operation: ApplianceOperation, already_applied: bool) -> dict:
    movements = session.scalars(
        select(ApplianceMovement)
        .where(ApplianceMovement.operation_id == operation.id)
        .order_by(ApplianceMovement.id)
    )
    return {
        "id": operation.id,
        "operation_key": operation.operation_key,
        "kind": operation.kind,
        "worker_id": operation.worker_id,
        "ticket_id": operation.ticket_id,
        "actor_id": operation.actor_id,
        "reason": operation.reason,
        "recorded_at": operation.recorded_at,
        "already_applied": already_applied,
        "movements": [
            {
                "appliance_id": m.appliance_id,
                "quantity": m.quantity,
                "ticket_id": m.ticket_id,
                "from_office_id": m.from_office_id,
                "from_worker_id": m.from_worker_id,
                "to_office_id": m.to_office_id,
                "to_worker_id": m.to_worker_id,
            }
            for m in movements
        ],
    }


def replay(session: Session, key: str, kind: str, request: dict) -> dict | None:
    """A repeated key returns the first receipt; a different request under it is refused."""
    operation = session.scalar(
        select(ApplianceOperation).where(ApplianceOperation.operation_key == key)
    )
    if operation is None:
        return None
    if operation.kind != kind or operation.request != request:
        raise InventoryError(
            "operation_key_conflict",
            "Ключ операции уже использован для другого запроса",
            operation_id=operation.id,
        )
    return receipt(session, operation, already_applied=True)


def record(session: Session, kind: str, key: str, actor_id, movements, **fields):
    operation = ApplianceOperation(operation_key=key, kind=kind, actor_id=actor_id, **fields)
    session.add(operation)
    session.flush()
    for movement in movements:
        session.add(ApplianceMovement(operation_id=operation.id, **movement))
    session.flush()
    return operation


def ticket_lines(session: Session, worker_id: int, day: date) -> list[dict]:
    """Allocations of the engineer's open tickets of the day that are still in the office."""
    rows = session.execute(
        text(f"""
            SELECT ta.ticket_id, ta.appliance_id, ta.office_id, ta.quantity
            FROM ticket_appliances ta
            JOIN tickets t ON t.id = ta.ticket_id AND t.assigned_worker_id = :worker
            LEFT JOIN ticket_appliance_states s
              ON s.ticket_id = ta.ticket_id AND s.appliance_id = ta.appliance_id
            WHERE s.ticket_id IS NULL AND t.status IN ('planned', 'in_progress')
              AND {TICKET_DAY} = :day
            ORDER BY ta.ticket_id, ta.appliance_id
        """),
        {"worker": worker_id, "day": day},
    ).mappings()
    return [{**row, "purpose": "ticket"} for row in rows]


def reserve_lines(session: Session, worker: dict, free: dict[int, int]) -> list[dict]:
    """Top up to the office norm; units already free on hand count toward it."""
    if worker["office_id"] is None:
        return []
    norms = session.scalars(
        select(OfficeKitReserve)
        .where(OfficeKitReserve.office_id == worker["office_id"])
        .order_by(OfficeKitReserve.appliance_id)
    )
    return [
        {
            "ticket_id": None,
            "appliance_id": norm.appliance_id,
            "office_id": norm.office_id,
            "quantity": norm.quantity - free.get(norm.appliance_id, 0),
            "purpose": "reserve",
        }
        for norm in norms
        if norm.quantity > free.get(norm.appliance_id, 0)
    ]


def shortages(session: Session, lines: list[dict]) -> list[dict]:
    needs: dict[tuple[int, int], list[int]] = {}
    for line in lines:
        need = needs.setdefault((line["office_id"], line["appliance_id"]), [0, 0])
        need[0 if line["ticket_id"] else 1] += line["quantity"]
    result = []
    for (office_id, appliance_id), (reserved_units, extra) in sorted(needs.items()):
        row = session.get(ApplianceStock, (office_id, appliance_id))
        stock = row.stock if row else 0
        reserved = repository.get_reserved_stock_for_office(session, office_id, appliance_id)
        # Ticket units are already inside the reservation; extra units need free stock.
        if stock < reserved_units + extra or stock - reserved < extra:
            result.append(
                {
                    "office_id": office_id,
                    "appliance_id": appliance_id,
                    "stock": stock,
                    "reserved": reserved,
                    "requested": reserved_units + extra,
                }
            )
    return result


def worker_equipment(session: Session, worker_id: int, day: date) -> dict:
    worker = find_worker(session, worker_id)
    held, used = on_hand(session, worker_id), committed(session, worker_id)
    free = {a: max(held.get(a, 0) - used.get(a, 0), 0) for a in held.keys() | used.keys()}
    lines = ticket_lines(session, worker_id, day) + reserve_lines(session, worker, free)
    appliances = {
        a.id: a
        for a in session.scalars(
            select(Appliance).where(
                Appliance.id.in_(held.keys() | used.keys() | {x["appliance_id"] for x in lines})
            )
        )
    }
    return {
        "worker_id": worker_id,
        "office_id": worker["office_id"],
        "date": day,
        "items": [
            {
                "appliance_id": a,
                "name": appliances[a].name,
                "type": appliances[a].type,
                "unit": appliances[a].unit,
                "on_hand": held.get(a, 0),
                "committed": used.get(a, 0),
                "free": free[a],
            }
            for a in sorted(held.keys() | used.keys())
        ],
        "to_issue": [
            {
                **line,
                "name": appliances[line["appliance_id"]].name,
                "unit": appliances[line["appliance_id"]].unit,
            }
            for line in lines
        ],
        "shortages": shortages(session, lines),
    }


def issue_kit(session: Session, worker_id: int, day: date, key: str, actor_id: int) -> dict:
    """Issue the day's kit: allocations of assigned tickets plus the office reserve norm."""
    request = {"worker_id": worker_id, "date": day.isoformat()}
    if (done := replay(session, key, "issue", request)) is not None:
        return done
    worker = find_worker(session, worker_id)
    lines = ticket_lines(session, worker_id, day)
    lines += reserve_lines(session, worker, free_units(session, worker_id))
    if not lines:
        raise InventoryError(
            "nothing_to_issue", "Комплект на эту дату уже на руках: выдавать нечего"
        )
    if short := shortages(session, lines):
        raise InventoryError(
            "insufficient_stock",
            "На складе офиса не хватает оборудования для комплекта",
            shortages=short,
        )
    for line in lines:
        change_stock(session, line["office_id"], line["appliance_id"], -line["quantity"])
        change_on_hand(session, worker_id, line["appliance_id"], line["quantity"])
        if line["ticket_id"]:
            session.add(
                TicketApplianceState(
                    ticket_id=line["ticket_id"],
                    appliance_id=line["appliance_id"],
                    holder_worker_id=worker_id,
                )
            )
    operation = record(
        session,
        "issue",
        key,
        actor_id,
        [
            {
                "appliance_id": line["appliance_id"],
                "quantity": line["quantity"],
                "ticket_id": line["ticket_id"],
                "from_office_id": line["office_id"],
                "to_worker_id": worker_id,
            }
            for line in lines
        ],
        worker_id=worker_id,
        request=request,
    )
    return receipt(session, operation, already_applied=False)


def return_equipment(session: Session, worker_id: int, data, actor_id: int) -> dict:
    """Explicit return to an office: free units, or whole allocations released from tickets."""
    request = {
        "worker_id": worker_id,
        "office_id": data.office_id,
        "items": sorted([i.appliance_id, i.quantity] for i in data.items),
        "ticket_ids": sorted(data.ticket_ids),
    }
    key = data.operation_key
    if (done := replay(session, key, "return", request)) is not None:
        return done
    worker = find_worker(session, worker_id)
    office_id = data.office_id or worker["office_id"]
    if data.items and office_id is None:
        raise InventoryError(
            "office_required", "Инженер не состоит в бригаде: укажите офис возврата", 422
        )
    if office_id is not None and session.get(Office, office_id) is None:
        raise InventoryError("office_not_found", f"Офис №{office_id} не найден", 404)
    movements = []
    for ticket_id in sorted(data.ticket_ids):
        states = session.scalars(
            select(TicketApplianceState)
            .where(
                TicketApplianceState.ticket_id == ticket_id,
                TicketApplianceState.holder_worker_id == worker_id,
                TicketApplianceState.consumed_operation_id.is_(None),
            )
            .order_by(TicketApplianceState.appliance_id)
            .with_for_update()
        ).all()
        if not states:
            raise InventoryError(
                "ticket_equipment_not_held",
                f"У инженера №{worker_id} нет выданного оборудования заявки №{ticket_id}",
                ticket_id=ticket_id,
            )
        for state in states:
            allocation = session.get(TicketAppliance, (ticket_id, state.appliance_id))
            change_on_hand(session, worker_id, state.appliance_id, -allocation.quantity)
            change_stock(session, allocation.office_id, state.appliance_id, allocation.quantity)
            movements.append(
                {
                    "appliance_id": state.appliance_id,
                    "quantity": allocation.quantity,
                    "ticket_id": ticket_id,
                    "from_worker_id": worker_id,
                    "to_office_id": allocation.office_id,
                }
            )
            session.delete(state)
    session.flush()
    free = free_units(session, worker_id)
    for item in sorted(data.items, key=lambda i: i.appliance_id):
        if item.quantity > free.get(item.appliance_id, 0):
            raise InventoryError(
                "equipment_committed",
                f"Свободно на руках {free.get(item.appliance_id, 0)}"
                f" «{name(session, item.appliance_id)}»: остальное закреплено за открытыми"
                " заявками, верните их отдельно по номерам заявок",
                appliance_id=item.appliance_id,
                requested=item.quantity,
                free=free.get(item.appliance_id, 0),
            )
        change_on_hand(session, worker_id, item.appliance_id, -item.quantity)
        change_stock(session, office_id, item.appliance_id, item.quantity)
        movements.append(
            {
                "appliance_id": item.appliance_id,
                "quantity": item.quantity,
                "from_worker_id": worker_id,
                "to_office_id": office_id,
            }
        )
    operation = record(
        session, "return", key, actor_id, movements, worker_id=worker_id, request=request
    )
    return receipt(session, operation, already_applied=False)


def allocations_with_state(session: Session, ticket_id: int):
    return session.execute(
        select(TicketAppliance, Appliance.type, TicketApplianceState)
        .join(Appliance, Appliance.id == TicketAppliance.appliance_id)
        .outerjoin(
            TicketApplianceState,
            (TicketApplianceState.ticket_id == TicketAppliance.ticket_id)
            & (TicketApplianceState.appliance_id == TicketAppliance.appliance_id),
        )
        .where(TicketAppliance.ticket_id == ticket_id)
        .order_by(TicketAppliance.appliance_id)
    ).all()


def consume_on_completion(session: Session, ticket_id: int, actor_id: int) -> None:
    """Write off every allocation exactly once: from the holder's hands or from the office."""
    movements, holders, consumed = [], set(), []
    for allocation, kind, state in allocations_with_state(session, ticket_id):
        if kind == ApplianceType.TOOL or (state and state.consumed_operation_id):
            continue
        holder = state.holder_worker_id if state else None
        if holder:
            change_on_hand(session, holder, allocation.appliance_id, -allocation.quantity)
            holders.add(holder)
        else:
            change_stock(
                session, allocation.office_id, allocation.appliance_id, -allocation.quantity
            )
        movements.append(
            {
                "appliance_id": allocation.appliance_id,
                "quantity": allocation.quantity,
                "ticket_id": ticket_id,
                "from_worker_id": holder,
                "from_office_id": None if holder else allocation.office_id,
            }
        )
        consumed.append((allocation, state))
    if not movements:
        return
    operation = record(
        session,
        "consume",
        f"consume:ticket:{ticket_id}:{uuid4().hex}",
        actor_id,
        movements,
        worker_id=holders.pop() if len(holders) == 1 else None,
        ticket_id=ticket_id,
    )
    for allocation, state in consumed:
        if state is None:
            session.add(
                TicketApplianceState(
                    ticket_id=ticket_id,
                    appliance_id=allocation.appliance_id,
                    consumed_operation_id=operation.id,
                )
            )
        else:
            state.consumed_operation_id = operation.id
    session.flush()


def restore_ticket_equipment(session: Session, ticket_id: int, data, actor_id: int) -> dict:
    """Explicit compensation after a reopen: units come back from the client to their source."""
    request = {"ticket_id": ticket_id, "reason": data.reason}
    if (done := replay(session, data.operation_key, "restore", request)) is not None:
        return done
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise InventoryError("ticket_not_found", f"Заявка №{ticket_id} не найдена", 404)
    if ticket.status == "completed":
        raise InventoryError(
            "ticket_completed", "Возврат от клиента оформляется после переоткрытия заявки"
        )
    movements = []
    for allocation, _, state in allocations_with_state(session, ticket_id):
        if state is None or state.consumed_operation_id is None:
            continue
        source = session.scalar(
            select(ApplianceMovement).where(
                ApplianceMovement.operation_id == state.consumed_operation_id,
                ApplianceMovement.appliance_id == allocation.appliance_id,
            )
        )
        if source.from_worker_id:
            change_on_hand(session, source.from_worker_id, source.appliance_id, source.quantity)
        else:
            change_stock(session, source.from_office_id, source.appliance_id, source.quantity)
        movements.append(
            {
                "appliance_id": source.appliance_id,
                "quantity": source.quantity,
                "ticket_id": ticket_id,
                "to_worker_id": source.from_worker_id,
                "to_office_id": source.from_office_id,
            }
        )
        state.consumed_operation_id = None
        if state.holder_worker_id is None:
            session.delete(state)
    if not movements:
        raise InventoryError(
            "nothing_to_restore", f"По заявке №{ticket_id} нет списанного оборудования"
        )
    session.flush()
    operation = record(
        session,
        "restore",
        data.operation_key,
        actor_id,
        movements,
        ticket_id=ticket_id,
        reason=data.reason,
        request=request,
    )
    return receipt(session, operation, already_applied=False)


def shift_started(worker: dict, moment: datetime, now: datetime) -> bool:
    """Has the shift that serves this visit already begun (the engineer left the office)?"""
    local = moment.astimezone(MOSCOW)
    start, end = worker["workshift_start"], worker["workshift_end"]
    day = local.date()
    if end <= start and local.time() < end:
        day -= timedelta(days=1)
    return now >= datetime.combine(day, start, MOSCOW)


def check_reassignment(
    session: Session, ticket_id: int, worker_ids: list[int], now: datetime | None = None
) -> None:
    """Units on hand never move by themselves; a departed engineer needs them already on hand."""
    now = now or datetime.now(MOSCOW)
    ticket = session.get(Ticket, ticket_id)
    moment = ticket.planned_start_at or ticket.visit_window_start
    rows = [
        (allocation, state)
        for allocation, _, state in allocations_with_state(session, ticket_id)
        if not (state and state.consumed_operation_id)
    ]
    if not rows or not worker_ids:
        return
    workers = {w: find_worker(session, w) for w in worker_ids}
    free = {w: free_units(session, w) for w in worker_ids}
    for allocation, state in rows:
        holder = state.holder_worker_id if state else None
        appliance_id, quantity = allocation.appliance_id, allocation.quantity
        if holder in worker_ids:
            continue
        if holder is None and any(not shift_started(workers[w], moment, now) for w in worker_ids):
            continue
        taker = next(
            (w for w in sorted(worker_ids) if free[w].get(appliance_id, 0) >= quantity), None
        )
        if taker is not None:
            free[taker][appliance_id] -= quantity
            if state is None:
                session.add(
                    TicketApplianceState(
                        ticket_id=ticket_id, appliance_id=appliance_id, holder_worker_id=taker
                    )
                )
            else:
                state.holder_worker_id = taker
            continue
        item = f"«{name(session, appliance_id)}» × {quantity}"
        if holder is None:
            raise InventoryError(
                "equipment_not_on_hand",
                f"Смена уже началась, а {item} у исполнителя на руках нет:"
                " сначала оформите выдачу (пополнение комплекта)",
                ticket_id=ticket_id,
                appliance_id=appliance_id,
                quantity=quantity,
                worker_ids=sorted(worker_ids),
            )
        raise InventoryError(
            "equipment_held_by_worker",
            f"{item} для заявки на руках у инженера №{holder}: оформите возврат"
            " или выдачу новому исполнителю",
            ticket_id=ticket_id,
            appliance_id=appliance_id,
            quantity=quantity,
            holder_worker_id=holder,
        )
    session.flush()


def operations(session: Session, *, worker_id=None, ticket_id=None, limit=50) -> list[dict]:
    statement = select(ApplianceOperation).order_by(ApplianceOperation.id.desc()).limit(limit)
    if worker_id is not None:
        statement = statement.where(ApplianceOperation.worker_id == worker_id)
    if ticket_id is not None:
        statement = statement.where(ApplianceOperation.ticket_id == ticket_id)
    return [receipt(session, op, already_applied=False) for op in session.scalars(statement)]


def kit_reserve(session: Session, office_id: int) -> list[dict]:
    if session.get(Office, office_id) is None:
        raise InventoryError("office_not_found", f"Офис №{office_id} не найден", 404)
    rows = session.execute(
        select(OfficeKitReserve, Appliance)
        .join(Appliance, Appliance.id == OfficeKitReserve.appliance_id)
        .where(OfficeKitReserve.office_id == office_id)
        .order_by(Appliance.name)
    ).all()
    return [
        {
            "office_id": office_id,
            "appliance_id": appliance.id,
            "name": appliance.name,
            "unit": appliance.unit,
            "quantity": norm.quantity,
        }
        for norm, appliance in rows
    ]


def set_kit_reserve(session: Session, office_id: int, appliance_id: int, quantity: int) -> dict:
    if session.get(Office, office_id) is None:
        raise InventoryError("office_not_found", f"Офис №{office_id} не найден", 404)
    appliance = session.get(Appliance, appliance_id)
    if appliance is None:
        raise InventoryError("appliance_not_found", f"Оборудование №{appliance_id} не найдено", 404)
    norm = session.get(OfficeKitReserve, (office_id, appliance_id))
    if quantity == 0:
        if norm is not None:
            session.delete(norm)
    elif norm is None:
        session.add(
            OfficeKitReserve(office_id=office_id, appliance_id=appliance_id, quantity=quantity)
        )
    else:
        norm.quantity = quantity
    session.flush()
    return {
        "office_id": office_id,
        "appliance_id": appliance_id,
        "name": appliance.name,
        "unit": appliance.unit,
        "quantity": quantity,
    }
