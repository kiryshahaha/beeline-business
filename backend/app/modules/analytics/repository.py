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
            (
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
                OR (
                    NOT EXISTS (
                        SELECT 1 FROM ticket_assignments AS unassigned_scope
                        WHERE unassigned_scope.ticket_id = t.id
                    )
                    AND t.service_area_id IN (
                        SELECT bld_sa.id
                        FROM offices AS off
                        JOIN locations AS off_loc ON off_loc.id = off.location_id
                        JOIN buildings AS off_bld ON off_bld.id = off_loc.building_id
                        JOIN service_areas AS bld_sa
                          ON bld_sa.code = 'district_' || off_bld.district_id
                        WHERE off.id = :office_id
                    )
                )
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


def find_brigades_workload(
    session: Session,
    *,
    brigade_id: int | None = None,
) -> list[RowMapping]:
    """Return active and completed-today ticket counts for visible brigades."""
    conditions: list[str] = []
    parameters: dict[str, object] = {
        "planned_status": "planned",
        "in_progress_status": "in_progress",
        "completed_status": "completed",
    }
    if brigade_id is not None:
        conditions.append("b.id = :brigade_id")
        parameters["brigade_id"] = brigade_id

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    query = text(
        f"""
        SELECT
            b.name AS brigade_name,
            COUNT(DISTINCT t.id) FILTER (
                WHERE t.status IN (:planned_status, :in_progress_status)
            ) AS active_tickets,
            COUNT(DISTINCT t.id) FILTER (
                WHERE t.status = :completed_status
                  AND t.updated_at >= date_trunc('day', CURRENT_TIMESTAMP)
            ) AS completed_today
        FROM brigades AS b
        LEFT JOIN brigade_members AS bm ON bm.brigade_id = b.id
        LEFT JOIN ticket_assignments AS ta ON ta.worker_id = bm.worker_id
        LEFT JOIN tickets AS t ON t.id = ta.ticket_id
        {where_clause}
        GROUP BY b.id, b.name
        ORDER BY b.id ASC
        """
    )
    return list(session.execute(query, parameters).mappings().all())


# Long comments are shortened for the feed; the full text stays in the ticket card.
COMMENT_EXCERPT_LENGTH = 140

# Every source of the feed reports the same columns, so one query can order them together.
ACTIVITY_FEED_SQL = """
    SELECT
        'ticket_created' AS kind,
        t.created_at AS occurred_at,
        t.id AS ticket_id,
        NULL::integer AS actor_id,
        NULL::integer AS worker_id,
        NULL::text AS previous_status,
        NULL::text AS new_status,
        NULL::integer AS comment_id,
        NULL::text AS comment_text
    FROM tickets AS t

    UNION ALL

    -- A status change writes one row per observer, so identical rows are grouped back into one.
    SELECT
        event.kind::text,
        event.created_at,
        event.ticket_id,
        (event.data ->> 'actor_id')::integer,
        (event.data ->> 'worker_id')::integer,
        event.data ->> 'previous_status',
        event.data ->> 'status',
        NULL::integer,
        NULL::text
    FROM notification_events AS event
    GROUP BY event.kind, event.created_at, event.ticket_id, event.data

    UNION ALL

    SELECT
        'comment_added',
        comment.created_at,
        comment.ticket_id,
        comment.author_id,
        NULL::integer,
        NULL::text,
        NULL::text,
        comment.id,
        comment.text
    FROM ticket_comments AS comment

    UNION ALL

    SELECT
        'comment_edited',
        comment.updated_at,
        comment.ticket_id,
        comment.author_id,
        NULL::integer,
        NULL::text,
        NULL::text,
        comment.id,
        comment.text
    FROM ticket_comments AS comment
    WHERE comment.updated_at > comment.created_at
"""

BRIGADE_SCOPE_SQL = """
    EXISTS (
        SELECT 1
        FROM ticket_assignments AS scope_assignment
        JOIN brigade_members AS scope_member
            ON scope_member.worker_id = scope_assignment.worker_id
        WHERE scope_assignment.ticket_id = t.id
          AND scope_member.brigade_id = :brigade_id
    )
"""


def find_recent_activity(
    session: Session, *, limit: int, offset: int, brigade_id: int | None = None
) -> list[RowMapping]:
    """Return the newest changes across tickets, assignments, statuses and comments."""
    parameters: dict[str, object] = {
        "limit": limit,
        "offset": offset,
        "excerpt_length": COMMENT_EXCERPT_LENGTH,
    }
    scope = ""
    if brigade_id is not None:
        scope = f"WHERE {BRIGADE_SCOPE_SQL}"
        parameters["brigade_id"] = brigade_id

    # Only fixed SQL fragments are joined; every value is a bound parameter.
    query = text(f"""
        SELECT
            feed.kind,
            feed.occurred_at,
            feed.ticket_id,
            t.title AS ticket_title,
            t.status AS ticket_status,
            feed.previous_status,
            feed.new_status,
            feed.comment_id,
            left(feed.comment_text, :excerpt_length) AS comment_excerpt,
            length(feed.comment_text) > :excerpt_length AS comment_truncated,
            actor.id AS actor_id,
            actor.surname AS actor_surname,
            actor.name AS actor_name,
            actor.role AS actor_role,
            assignee.id AS assignee_id,
            assignee.surname AS assignee_surname,
            assignee.name AS assignee_name,
            assignee.role AS assignee_role
        FROM ({ACTIVITY_FEED_SQL}) AS feed
        JOIN tickets AS t ON t.id = feed.ticket_id
        LEFT JOIN users AS actor ON actor.id = feed.actor_id
        LEFT JOIN users AS assignee ON assignee.id = feed.worker_id
        {scope}
        ORDER BY
            feed.occurred_at DESC,
            feed.ticket_id DESC,
            feed.kind DESC,
            feed.comment_id DESC NULLS LAST,
            feed.worker_id DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """)
    return list(session.execute(query, parameters).mappings().all())
