"""Parameterized SQL queries for ticket analytics."""

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.modules.analytics.schemas import AnalyticsPeriod

PERIOD_CONDITIONS = {
    AnalyticsPeriod.TODAY: "t.created_at >= date_trunc('day', CURRENT_TIMESTAMP)",
    AnalyticsPeriod.WEEK: "t.created_at >= date_trunc('week', CURRENT_TIMESTAMP)",
    AnalyticsPeriod.MONTH: "t.created_at >= date_trunc('month', CURRENT_TIMESTAMP)",
}


def find_tickets_summary(
    session: Session,
    *,
    period: AnalyticsPeriod,
    office_id: int | None = None,
    brigade_id: int | None = None,
) -> RowMapping:
    """Count tickets in a calendar period, optionally scoped to an office or brigade."""
    conditions = [PERIOD_CONDITIONS[period]]
    parameters: dict[str, object] = {
        "planned_status": "planned",
        "in_progress_status": "in_progress",
        "completed_status": "completed",
    }

    if brigade_id is not None:
        conditions.append(
            """
            EXISTS (
                SELECT 1
                FROM ticket_assignments AS scope_assignment
                JOIN brigade_members AS scope_member
                    ON scope_member.worker_id = scope_assignment.worker_id
                WHERE scope_assignment.ticket_id = t.id
                  AND scope_member.brigade_id = :brigade_id
            )
            """
        )
        parameters["brigade_id"] = brigade_id
    elif office_id is not None:
        conditions.append(
            """
            EXISTS (
                SELECT 1
                FROM ticket_assignments AS scope_assignment
                JOIN brigade_members AS scope_member
                    ON scope_member.worker_id = scope_assignment.worker_id
                JOIN brigades AS scope_brigade
                    ON scope_brigade.id = scope_member.brigade_id
                WHERE scope_assignment.ticket_id = t.id
                  AND scope_brigade.office_id = :office_id
            )
            """
        )
        parameters["office_id"] = office_id

    query = text(
        f"""
        SELECT
            COUNT(*) FILTER (
                WHERE t.status = :planned_status
                  AND NOT EXISTS (
                      SELECT 1
                      FROM ticket_assignments AS open_assignment
                      WHERE open_assignment.ticket_id = t.id
                  )
            ) AS open,
            COUNT(*) FILTER (
                WHERE t.status = :planned_status
                  AND EXISTS (
                      SELECT 1
                      FROM ticket_assignments AS assigned_ticket
                      WHERE assigned_ticket.ticket_id = t.id
                  )
            ) AS assigned,
            COUNT(*) FILTER (WHERE t.status = :in_progress_status) AS in_progress,
            COUNT(*) FILTER (WHERE t.status = :completed_status) AS completed
        FROM tickets AS t
        WHERE {" AND ".join(conditions)}
        """
    )
    return session.execute(query, parameters).mappings().one()
