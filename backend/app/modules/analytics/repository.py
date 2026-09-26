"""Parameterized SQL for analytics.

Every period is a half-open Moscow interval passed in by the caller, so no query here
depends on the PostgreSQL session timezone.
"""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

# A ticket's area is its own, or that of the building it is in. An office serves its own
# configured area, or that of the building it is in.
TICKET_AREA_SQL = "COALESCE(t.service_area_id, ticket_building.service_area_id)"
TICKET_BUILDING_JOIN = """
    JOIN locations AS ticket_location ON ticket_location.id = t.location_id
    JOIN buildings AS ticket_building ON ticket_building.id = ticket_location.building_id
"""
OFFICE_AREAS_SQL = """
    SELECT COALESCE(office.service_area_id, office_building.service_area_id)
    FROM offices AS office
    JOIN locations AS office_location ON office_location.id = office.location_id
    JOIN buildings AS office_building ON office_building.id = office_location.building_id
"""

# The moment a ticket was completed: the recorded actual time, else the completion
# event. `updated_at` is never used — editing a closed ticket is not a completion.
COMPLETED_AT_SQL = """
    COALESCE(
        t.actual_completed_at,
        (
            SELECT max(done.occurred_at)
            FROM work_events AS done
            WHERE done.ticket_id = t.id AND done.event_type = 'complete'
        )
    )
"""

# Assigned work belongs to the office whose brigade holds it; the queue still waiting
# for an engineer belongs to the office's area, whoever may take it later.
OFFICE_SCOPE_SQL = f"""
    (
        EXISTS (
            SELECT 1
            FROM brigade_members AS scope_member
            JOIN brigades AS scope_brigade ON scope_brigade.id = scope_member.brigade_id
            WHERE scope_member.worker_id = t.assigned_worker_id
              AND scope_brigade.office_id = :office_id
        )
        OR (
            t.assigned_worker_id IS NULL
            AND {TICKET_AREA_SQL} IN ({OFFICE_AREAS_SQL} WHERE office.id = :office_id)
        )
    )
"""

# A foreman answers for one brigade: its assigned work plus the queue waiting in the
# area of the brigade's office. Other brigades' work stays invisible.
FOREMAN_SCOPE_SQL = f"""
    (
        EXISTS (
            SELECT 1
            FROM brigade_members AS scope_member
            WHERE scope_member.worker_id = t.assigned_worker_id
              AND scope_member.brigade_id = :brigade_id
        )
        OR (
            t.assigned_worker_id IS NULL
            AND {TICKET_AREA_SQL} IN (
                {OFFICE_AREAS_SQL}
                JOIN brigades AS scope_brigade ON scope_brigade.office_id = office.id
                WHERE scope_brigade.id = :brigade_id
            )
        )
    )
"""


def _scope(office_id: int | None, brigade_id: int | None) -> tuple[str, dict]:
    if brigade_id is not None:
        return FOREMAN_SCOPE_SQL, {"brigade_id": brigade_id}
    if office_id is not None:
        return OFFICE_SCOPE_SQL, {"office_id": office_id}
    return "TRUE", {}


def find_tickets_summary(
    session: Session,
    *,
    period_start: datetime,
    period_end: datetime,
    plan_start: datetime,
    plan_end: datetime,
    office_id: int | None = None,
    brigade_id: int | None = None,
) -> RowMapping:
    """Current state, created, completed and planned counts of one scope in one pass."""
    scope, parameters = _scope(office_id, brigade_id)
    parameters |= {
        "period_start": period_start,
        "period_end": period_end,
        "plan_start": plan_start,
        "plan_end": plan_end,
    }
<<<<<<< HEAD

    if brigade_id is not None:
        conditions.append(
            """
            EXISTS (
                SELECT 1
                FROM brigade_members AS scope_member
                WHERE scope_member.worker_id = t.assigned_worker_id
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
                    FROM brigade_members AS scope_member
                    JOIN brigades AS scope_brigade
                        ON scope_brigade.id = scope_member.brigade_id
                    WHERE scope_member.worker_id = t.assigned_worker_id
                      AND scope_brigade.office_id = :office_id
                )
                OR (
                    t.assigned_worker_id IS NULL
                    AND t.service_area_id IN (
                        SELECT bld_sa.id
                        FROM offices AS off
                        JOIN locations AS off_loc ON off_loc.id = off.location_id
                        JOIN buildings AS off_bld ON off_bld.id = off_loc.building_id
                        JOIN service_areas AS bld_sa
                          ON bld_sa.id = off_bld.service_area_id
                        WHERE off.id = :office_id
                    )
                )
            )
            """
        )
        parameters["office_id"] = office_id

=======
    # Only fixed SQL fragments are joined; every value is a bound parameter.
>>>>>>> origin/main
    query = text(
        f"""
        SELECT
            COUNT(*) FILTER (
                WHERE t.status = 'planned' AND t.assigned_worker_id IS NULL
            ) AS open_unassigned,
            COUNT(*) FILTER (
                WHERE t.status = 'planned' AND t.assigned_worker_id IS NOT NULL
            ) AS open_assigned,
            COUNT(*) FILTER (WHERE t.status = 'in_progress') AS in_progress,
            COUNT(*) FILTER (
                WHERE t.created_at >= :period_start AND t.created_at < :period_end
            ) AS created_in_period,
            COUNT(*) FILTER (
                WHERE t.status = 'completed'
                  AND {COMPLETED_AT_SQL} >= :period_start
                  AND {COMPLETED_AT_SQL} < :period_end
            ) AS completed_in_period,
            COUNT(*) FILTER (
                WHERE t.planned_start_at >= :plan_start AND t.planned_start_at < :plan_end
            ) AS planned_for_date
        FROM tickets AS t
        {TICKET_BUILDING_JOIN}
        WHERE {scope}
        """
    )
    return session.execute(query, parameters).mappings().one()


def find_brigade_members(session: Session, *, brigade_id: int | None = None) -> list[RowMapping]:
    """Visible brigades with their active engineers and the shift each one works.

    A brigade without members is still returned, with a NULL worker.
    """
    scope = "WHERE b.id = :brigade_id" if brigade_id is not None else ""
    parameters = {"brigade_id": brigade_id} if brigade_id is not None else {}
    # Only fixed SQL fragments are joined; every value is a bound parameter.
    return list(
        session.execute(
            text(f"""
                SELECT
                    b.id AS brigade_id, b.name AS brigade_name,
                    u.id, w.workshift_start, w.workshift_end, w.service_area_id
                FROM brigades AS b
                LEFT JOIN brigade_members AS member ON member.brigade_id = b.id
                LEFT JOIN users AS u
                    ON u.id = member.worker_id
                   AND u.role = 'worker'
                   AND u.archived_at IS NULL
                LEFT JOIN workers AS w ON w.user_id = u.id
                {scope}
                ORDER BY b.id, u.id
            """),
            parameters,
        )
        .mappings()
        .all()
    )


def find_completed_by_brigade(
    session: Session, *, day_start: datetime, day_end: datetime, brigade_id: int | None = None
) -> dict[int, int]:
    scope = "AND member.brigade_id = :brigade_id" if brigade_id is not None else ""
    parameters: dict[str, object] = {"day_start": day_start, "day_end": day_end}
    if brigade_id is not None:
        parameters["brigade_id"] = brigade_id
    rows = session.execute(
        text(f"""
            SELECT member.brigade_id, COUNT(DISTINCT t.id) AS completed
            FROM tickets AS t
            JOIN brigade_members AS member ON member.worker_id = t.assigned_worker_id
            WHERE t.status = 'completed'
              AND {COMPLETED_AT_SQL} >= :day_start
              AND {COMPLETED_AT_SQL} < :day_end
              {scope}
            GROUP BY member.brigade_id
        """),
        parameters,
    ).mappings()
    return {row["brigade_id"]: row["completed"] for row in rows}


# Long comments are shortened for the feed; the full text stays in the ticket card.
COMMENT_EXCERPT_LENGTH = 140

# The feed reads domain records, not the delivery queue. `work_events` is the lifecycle
# log with its author, `ticket_assignment_events` records every change of assignee with
# its author and path. `notification_events` only says what was pushed to whom — one row
# per recipient, rows can be pruned after delivery — so it is not a source of history.
# Comments keep only their current text, so an edit is reported as an edit and the
# excerpt is today's wording; the feed does not claim a full audit of comment text.
ACTIVITY_FEED_SQL = """
    SELECT
        CASE event.event_type
            WHEN 'new_ticket' THEN 'ticket_created'
            WHEN 'cancel_ticket' THEN 'ticket_cancelled'
            WHEN 'window_change' THEN 'ticket_rescheduled'
            WHEN 'redirect' THEN 'worker_redirected'
            WHEN 'progress_delay' THEN 'ticket_delayed'
            ELSE 'ticket_status_changed'
        END AS kind,
        event.occurred_at,
        event.ticket_id,
        event.actor_id,
        NULL::integer AS worker_id,
        NULL::integer AS previous_worker_id,
        NULL::text AS assignment_source,
        event.previous_state,
        event.new_state,
        event.reason,
        NULL::integer AS comment_id,
        NULL::text AS comment_text
    FROM work_events AS event
    -- Assignment has its own, complete record below; the lifecycle log only saw the
    -- first one. Marking an engineer unavailable is a worker-level fact: its effect on
    -- tickets, releasing them, is in the assignment history with the source line_status.
    WHERE event.ticket_id IS NOT NULL
      AND event.event_type NOT IN ('assign', 'worker_unavailable')

    UNION ALL

    -- A ticket created before the lifecycle log existed still appears once.
    SELECT
        'ticket_created', t.created_at, t.id, NULL::integer, NULL::integer, NULL::integer,
        NULL::text, NULL::text, NULL::text, NULL::text, NULL::integer, NULL::text
    FROM tickets AS t
    WHERE NOT EXISTS (
        SELECT 1
        FROM work_events AS created
        WHERE created.ticket_id = t.id AND created.event_type = 'new_ticket'
    )

    UNION ALL

    SELECT
        CASE
            WHEN assignment.source = 'plan' THEN 'plan_applied'
            WHEN assignment.new_worker_id IS NULL THEN 'ticket_unassigned'
            WHEN assignment.previous_worker_id IS NULL THEN 'ticket_assigned'
            ELSE 'ticket_reassigned'
        END,
        assignment.occurred_at,
        assignment.ticket_id,
        assignment.actor_id,
        assignment.new_worker_id,
        assignment.previous_worker_id,
        assignment.source,
        NULL::text,
        NULL::text,
        NULL::text,
        NULL::integer,
        NULL::text
    FROM ticket_assignment_events AS assignment

    UNION ALL

    SELECT
        'comment_added', comment.created_at, comment.ticket_id, comment.author_id,
        NULL::integer, NULL::integer, NULL::text, NULL::text, NULL::text, NULL::text,
        comment.id, comment.text
    FROM ticket_comments AS comment

    UNION ALL

    SELECT
        'comment_edited', comment.updated_at, comment.ticket_id, comment.author_id,
        NULL::integer, NULL::integer, NULL::text, NULL::text, NULL::text, NULL::text,
        comment.id, comment.text
    FROM ticket_comments AS comment
    WHERE comment.updated_at > comment.created_at
"""

# The feed follows the same visibility as the summary: a foreman sees the brigade's work
# and the queue of the brigade office's area, including a ticket that has since moved on
# from one of the brigade's engineers.
FEED_FOREMAN_SCOPE_SQL = f"""
    (
        {FOREMAN_SCOPE_SQL}
        OR EXISTS (
            SELECT 1
            FROM brigade_members AS former_member
            WHERE former_member.brigade_id = :brigade_id
              AND former_member.worker_id IN (feed.worker_id, feed.previous_worker_id)
        )
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
        scope = f"WHERE {FEED_FOREMAN_SCOPE_SQL}"
        parameters["brigade_id"] = brigade_id

    # Only fixed SQL fragments are joined; every value is a bound parameter.
    query = text(f"""
        SELECT
            feed.kind,
            feed.occurred_at,
            feed.ticket_id,
            feed.reason,
            feed.assignment_source,
            feed.previous_state,
            feed.new_state,
            t.title AS ticket_title,
            t.work_type_id,
            COALESCE(wt.name, t.work_type) AS work_type,
            t.category,
            t.priority,
            t.received_at,
            t.sla_deadline_at,
            t.status AS ticket_status,
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
            assignee.role AS assignee_role,
            previous.id AS previous_id,
            previous.surname AS previous_surname,
            previous.name AS previous_name,
            previous.role AS previous_role
        FROM ({ACTIVITY_FEED_SQL}) AS feed
        JOIN tickets AS t ON t.id = feed.ticket_id
        {TICKET_BUILDING_JOIN}
        LEFT JOIN work_types AS wt ON wt.id = t.work_type_id
        LEFT JOIN users AS actor ON actor.id = feed.actor_id
        LEFT JOIN users AS assignee ON assignee.id = feed.worker_id
        LEFT JOIN users AS previous ON previous.id = feed.previous_worker_id
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


def find_fast_stats(
    session: Session,
    *,
    office_id: int | None = None,
) -> dict:
    """Calculate fast operational stats for today."""

    scope_cond_tickets = ""
    scope_cond_workers = ""
    scope_cond_brigades = ""
    parameters = {}

    if office_id is not None:
        scope_cond_tickets = """
            AND (
                EXISTS (
                    SELECT 1
                    FROM brigade_members AS scope_member
                    JOIN brigades AS scope_brigade ON scope_brigade.id = scope_member.brigade_id
                    WHERE scope_member.worker_id = t.assigned_worker_id
                      AND scope_brigade.office_id = :office_id
                )
                OR (
                    t.assigned_worker_id IS NULL
                    AND t.service_area_id = (
                        SELECT off.service_area_id
                        FROM offices AS off
                        WHERE off.id = :office_id
                    )
                )
            )
        """
        scope_cond_workers = """
            AND EXISTS (
                SELECT 1 
                FROM brigade_members bm 
                JOIN brigades b ON b.id = bm.brigade_id 
                WHERE bm.worker_id = w.user_id AND b.office_id = :office_id
            )
        """
        scope_cond_brigades = " WHERE b.office_id = :office_id "
        parameters["office_id"] = office_id

    query = f"""
    WITH today_tickets AS (
        SELECT 
            t.id AS ticket_id,
            t.status,
            t.sla_deadline_at,
            t.visit_window_end,
            t.estimated_duration_minutes,
            t.actual_started_at,
            CASE 
                WHEN t.status = 'planned' 
                     AND t.visit_window_end IS NOT NULL 
                     AND CURRENT_TIMESTAMP > t.visit_window_end 
                THEN EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - t.visit_window_end)) / 60
                WHEN t.status = 'in_progress' 
                     AND t.actual_started_at IS NOT NULL 
                     AND t.estimated_duration_minutes IS NOT NULL 
                     AND CURRENT_TIMESTAMP > (
                        t.actual_started_at + t.estimated_duration_minutes * interval '1 minute'
                     )
                THEN EXTRACT(EPOCH FROM (
                    CURRENT_TIMESTAMP - (
                        t.actual_started_at + t.estimated_duration_minutes * interval '1 minute'
                    )
                )) / 60
                ELSE 0
            END AS delay_minutes
        FROM tickets t
        WHERE t.created_at >= date_trunc('day', CURRENT_TIMESTAMP)
        {scope_cond_tickets}
    ),
    ticket_stats AS (
        SELECT
            COUNT(*) AS total_today,
            COUNT(*) FILTER (
                WHERE status IN ('completed', 'wont_fix') 
                   OR (sla_deadline_at IS NULL OR sla_deadline_at >= CURRENT_TIMESTAMP)
            ) AS compliant_today,
            COUNT(*) FILTER (WHERE delay_minutes > 0) AS at_risk_count,
            COALESCE(AVG(delay_minutes) FILTER (WHERE delay_minutes > 0), 0) AS avg_delay,
            ARRAY_AGG(ticket_id) FILTER (WHERE delay_minutes > 0) AS at_risk_ids
        FROM today_tickets
    ),
    idle_workers AS (
        SELECT 
            COUNT(*) AS idle_count,
            ARRAY_AGG(w.user_id) AS idle_ids
        FROM workers w
        WHERE w.is_on_line = TRUE
          {scope_cond_workers}
          AND NOT EXISTS (
              SELECT 1 FROM tickets t 
              WHERE t.assigned_worker_id = w.user_id AND t.status IN ('planned', 'in_progress')
          )
    ),
    active_brigades AS (
        SELECT COUNT(DISTINCT b.id) AS active_count
        FROM brigades b
        {scope_cond_brigades}
    )
    SELECT 
        ts.total_today,
        ts.compliant_today,
        ts.at_risk_count,
        ts.avg_delay,
        ts.at_risk_ids,
        iw.idle_count,
        iw.idle_ids,
        ab.active_count
    FROM ticket_stats ts
    CROSS JOIN idle_workers iw
    CROSS JOIN active_brigades ab;
    """

    row = session.execute(text(query), parameters).mappings().one()

    total = row["total_today"]
    compliant = row["compliant_today"]
    compliance_percent = int((compliant / total * 100) if total > 0 else 100)

    return {
        "sla_compliance_percent": compliance_percent,
        "at_risk_tickets_count": row["at_risk_count"],
        "average_delay_minutes": int(row["avg_delay"]),
        "idle_workers_count": row["idle_count"],
        "at_risk_tickets_ids": list(row["at_risk_ids"] or []),
        "idle_workers_ids": list(row["idle_ids"] or []),
        "active_brigades_count": row["active_count"],
    }
