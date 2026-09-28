"""Read every stated area of tickets and engineers in one query and resolve it.

Planning, manual assignment, brigade membership and direct route saves use these
same functions, so one conflict yields the same code on every path.
"""

from collections.abc import Iterable

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.modules.service_areas.resolve import (
    ServiceAreaResolutionError,
    resolve_area,
    worker_signals,
)

# An office states an area only explicitly: its building's area is the geographic
# district of its address, which is not the operational area of the engineers.
WORKER_SIGNALS = text(
    """
    SELECT worker.user_id AS worker_id,
           worker.service_area_id AS own,
           division.service_area_id AS brigade,
           brigade_office.service_area_id AS brigade_office,
           stock_office.service_area_id AS stock_office
    FROM workers AS worker
    LEFT JOIN brigade_members AS membership ON membership.worker_id = worker.user_id
    LEFT JOIN brigades AS brigade ON brigade.id = membership.brigade_id
    LEFT JOIN divisions AS division ON division.id = brigade.division_id
    LEFT JOIN offices AS brigade_office ON brigade_office.id = brigade.office_id
    LEFT JOIN offices AS stock_office ON stock_office.id = worker.stock_office_id
    WHERE worker.user_id IN :worker_ids
    """
).bindparams(bindparam("worker_ids", expanding=True))

# The ticket's own area comes from its dataset or the dispatcher; the building's area
# is the default of its address and applies only when the ticket states none.
TICKET_AREAS = text(
    """
    SELECT ticket.id AS ticket_id,
           ticket.service_area_id AS own,
           building.service_area_id AS building
    FROM tickets AS ticket
    LEFT JOIN locations AS location ON location.id = ticket.location_id
    LEFT JOIN buildings AS building ON building.id = location.building_id
    WHERE ticket.id IN :ticket_ids
    """
).bindparams(bindparam("ticket_ids", expanding=True))


BRIGADE_SIGNALS = text(
    """
    SELECT division.service_area_id AS brigade, office.service_area_id AS brigade_office
    FROM brigades AS brigade
    JOIN divisions AS division ON division.id = brigade.division_id
    LEFT JOIN offices AS office ON office.id = brigade.office_id
    WHERE brigade.id = :brigade_id
    """
)


def resolve_brigade(session: Session, brigade_id: int) -> int | None:
    """The brigade's area; None when the brigade does not exist."""
    row = session.execute(BRIGADE_SIGNALS, {"brigade_id": brigade_id}).mappings().one_or_none()
    if row is None:
        return None
    return resolve_area(
        "brigade",
        brigade_id,
        {"brigade": row["brigade"], "brigade_office": row["brigade_office"]},
    )


def worker_signal_rows(session: Session, worker_ids: Iterable[int]) -> dict[int, dict]:
    ids = sorted(set(worker_ids))
    if not ids:
        return {}
    return {
        row["worker_id"]: worker_signals(
            row["own"], row["brigade"], row["brigade_office"], row["stock_office"]
        )
        for row in session.execute(WORKER_SIGNALS, {"worker_ids": ids}).mappings()
    }


def resolve_workers(
    session: Session, worker_ids: Iterable[int]
) -> tuple[dict[int, int], dict[int, ServiceAreaResolutionError]]:
    """Areas of known engineers and the reason for every one that has none or several."""
    areas, errors = {}, {}
    for worker_id, signals in worker_signal_rows(session, worker_ids).items():
        try:
            areas[worker_id] = resolve_area("worker", worker_id, signals)
        except ServiceAreaResolutionError as error:
            errors[worker_id] = error
    return areas, errors


def resolve_worker(session: Session, worker_id: int) -> int:
    areas, errors = resolve_workers(session, [worker_id])
    if worker_id in errors:
        raise errors[worker_id]
    if worker_id not in areas:
        raise ServiceAreaResolutionError("service_area_missing", "worker", worker_id)
    return areas[worker_id]


def consistency_report(session: Session) -> dict:
    """Every stored link that would block an assignment, with the conflicting IDs.

    Read-only: nothing is moved between areas. An engineer, a brigade or an open ticket
    listed here must be fixed in the directories before it can be planned.
    """
    worker_ids = session.execute(
        text(
            """
            SELECT worker.user_id
            FROM workers AS worker
            JOIN users AS account ON account.id = worker.user_id
            WHERE account.role = 'worker' AND account.archived_at IS NULL
            ORDER BY worker.user_id
            """
        )
    ).scalars()
    _, worker_errors = resolve_workers(session, worker_ids)
    brigades = []
    for row in session.execute(
        text(
            """
            SELECT brigade.id, division.service_area_id AS brigade,
                   office.service_area_id AS brigade_office
            FROM brigades AS brigade
            JOIN divisions AS division ON division.id = brigade.division_id
            LEFT JOIN offices AS office ON office.id = brigade.office_id
            WHERE office.service_area_id IS NOT NULL
              AND office.service_area_id <> division.service_area_id
            ORDER BY brigade.id
            """
        )
    ).mappings():
        brigades.append(
            {
                "code": "service_area_configuration_mismatch",
                "subject": "brigade",
                "subject_id": row["id"],
                "sources": {"brigade": row["brigade"], "brigade_office": row["brigade_office"]},
            }
        )
    open_tickets = (
        session.execute(
            text(
                """
            SELECT ticket.id, ticket.assigned_worker_id, ticket.brigade_id,
                   COALESCE(ticket.service_area_id, building.service_area_id) AS area,
                   division.service_area_id AS brigade_area
            FROM tickets AS ticket
            JOIN locations AS location ON location.id = ticket.location_id
            JOIN buildings AS building ON building.id = location.building_id
            LEFT JOIN brigades AS brigade ON brigade.id = ticket.brigade_id
            LEFT JOIN divisions AS division ON division.id = brigade.division_id
            WHERE ticket.status IN ('planned', 'in_progress')
            ORDER BY ticket.id
            """
            )
        )
        .mappings()
        .all()
    )
    assigned_areas, assigned_errors = resolve_workers(
        session, {row["assigned_worker_id"] for row in open_tickets if row["assigned_worker_id"]}
    )
    tickets = []
    for row in open_tickets:
        if row["brigade_area"] is not None and row["brigade_area"] != row["area"]:
            tickets.append(
                {
                    "code": "service_area_mismatch",
                    "subject": "ticket",
                    "subject_id": row["id"],
                    "sources": {"ticket": row["area"], "brigade": row["brigade_area"]},
                }
            )
        worker_id = row["assigned_worker_id"]
        if worker_id is not None and worker_id not in assigned_errors:
            if assigned_areas.get(worker_id) != row["area"]:
                tickets.append(
                    {
                        "code": "service_area_mismatch",
                        "subject": "ticket",
                        "subject_id": row["id"],
                        "sources": {"ticket": row["area"], "worker": assigned_areas.get(worker_id)},
                    }
                )
    workers = [worker_errors[worker_id].details() for worker_id in sorted(worker_errors)]
    return {
        "consistent": not (workers or brigades or tickets),
        "workers": workers,
        "brigades": brigades,
        "tickets": tickets,
    }


def ticket_area(own: int | None, building: int | None) -> int | None:
    return own if own is not None else building


def resolve_tickets(
    session: Session, ticket_ids: Iterable[int]
) -> tuple[dict[int, int], dict[int, ServiceAreaResolutionError]]:
    ids = sorted(set(ticket_ids))
    areas, errors = {}, {}
    if not ids:
        return areas, errors
    for row in session.execute(TICKET_AREAS, {"ticket_ids": ids}).mappings():
        area = ticket_area(row["own"], row["building"])
        if area is None:
            errors[row["ticket_id"]] = ServiceAreaResolutionError(
                "service_area_missing", "ticket", row["ticket_id"]
            )
        else:
            areas[row["ticket_id"]] = area
    return areas, errors


def resolve_ticket(session: Session, ticket_id: int) -> int:
    areas, errors = resolve_tickets(session, [ticket_id])
    if ticket_id in errors:
        raise errors[ticket_id]
    if ticket_id not in areas:
        raise ServiceAreaResolutionError("service_area_missing", "ticket", ticket_id)
    return areas[ticket_id]
