"""Literal, parameterized SQL for event history and push tokens."""

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session


def upsert_subscription(session: Session, user_id: int, token: str) -> RowMapping:
    return (
        session.execute(
            text("""
                INSERT INTO push_subscriptions (user_id, token)
                VALUES (:user_id, :token)
                ON CONFLICT (token) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    updated_at = now()
                RETURNING id, user_id, token, created_at, updated_at
            """),
            {"user_id": user_id, "token": token},
        )
        .mappings()
        .one()
    )


def delete_subscription(session: Session, user_id: int, token: str) -> bool:
    result = session.execute(
        text("""
            DELETE FROM push_subscriptions
            WHERE user_id = :user_id AND token = :token
        """),
        {"user_id": user_id, "token": token},
    )
    return (result.rowcount or 0) > 0


def list_events(
    session: Session,
    recipient_id: int,
    *,
    limit: int,
    offset: int,
) -> list[RowMapping]:
    return list(
        session.execute(
            text("""
                SELECT id, recipient_id, ticket_id, kind, data, created_at
                FROM notification_events
                WHERE recipient_id = :recipient_id
                ORDER BY id DESC
                LIMIT :limit OFFSET :offset
            """),
            {"recipient_id": recipient_id, "limit": limit, "offset": offset},
        )
        .mappings()
        .all()
    )


def claim_pending_events(session: Session, limit: int) -> list[RowMapping]:
    return list(
        session.execute(
            text("""
                WITH claimed AS (
                    SELECT id
                    FROM notification_events
                    WHERE (
                        (websocket_delivered_at IS NULL AND websocket_missed_at IS NULL)
                        OR push_delivered_at IS NULL
                    )
                      AND next_attempt_at <= now()
                    ORDER BY id
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE notification_events AS event
                SET next_attempt_at = now() + interval '30 seconds'
                FROM claimed
                WHERE event.id = claimed.id
                RETURNING
                    event.id, event.recipient_id, event.ticket_id, event.kind, event.data,
                    event.created_at, event.websocket_delivered_at, event.websocket_missed_at,
                    event.push_delivered_at, event.attempt_count
            """),
            {"limit": limit},
        )
        .mappings()
        .all()
    )


def list_subscription_tokens(session: Session, user_id: int) -> list[str]:
    return list(
        session.execute(
            text("""
                SELECT token
                FROM push_subscriptions
                WHERE user_id = :user_id
                ORDER BY id
            """),
            {"user_id": user_id},
        ).scalars()
    )


def mark_websocket_missed(session: Session, event_id: int) -> None:
    """Nobody was connected to receive it live; the history replay will carry it."""
    session.execute(
        text("""
            UPDATE notification_events
            SET websocket_missed_at = now()
            WHERE id = :event_id
              AND websocket_delivered_at IS NULL
              AND websocket_missed_at IS NULL
        """),
        {"event_id": event_id},
    )


def list_events_after(
    session: Session, recipient_id: int, after_id: int, *, limit: int
) -> list[RowMapping]:
    """The recipient's events newer than `after_id`, oldest first, without gaps.

    Ids only grow, so a client that remembers the last id it saw can page forward from
    it; offset paging from the newest end shifts under new events and can skip one.
    """
    return list(
        session.execute(
            text("""
                SELECT id, recipient_id, ticket_id, kind, data, created_at
                FROM notification_events
                WHERE recipient_id = :recipient_id AND id > :after_id
                ORDER BY id
                LIMIT :limit
            """),
            {"recipient_id": recipient_id, "after_id": after_id, "limit": limit},
        )
        .mappings()
        .all()
    )


def mark_websocket_delivered(session: Session, event_id: int) -> None:
    session.execute(
        text("""
            UPDATE notification_events
            SET websocket_delivered_at = COALESCE(websocket_delivered_at, now())
            WHERE id = :event_id AND websocket_missed_at IS NULL
        """),
        {"event_id": event_id},
    )


def mark_push_delivered(session: Session, event_id: int) -> None:
    session.execute(
        text("""
            UPDATE notification_events
            SET push_delivered_at = COALESCE(push_delivered_at, now()), last_error = NULL
            WHERE id = :event_id
        """),
        {"event_id": event_id},
    )


def record_push_failure(
    session: Session,
    event_id: int,
    *,
    next_attempt_at,
    error: str,
) -> None:
    session.execute(
        text("""
            UPDATE notification_events
            SET attempt_count = attempt_count + 1,
                next_attempt_at = :next_attempt_at,
                last_error = :error
            WHERE id = :event_id
        """),
        {"event_id": event_id, "next_attempt_at": next_attempt_at, "error": error[:1000]},
    )


def delete_subscription_tokens(session: Session, tokens: set[str]) -> None:
    if not tokens:
        return
    session.execute(
        text("DELETE FROM push_subscriptions WHERE token = ANY(:tokens)"),
        {"tokens": list(tokens)},
    )
