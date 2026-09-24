"""Literal SQL queries for refresh token lifecycle."""

from datetime import datetime

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session


def add_refresh_token(
    session: Session, user_id: int, token_hash: str, expires_at: datetime
) -> None:
    session.execute(
        text("""
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
            VALUES (:user_id, :token_hash, :expires_at)
        """),
        {"user_id": user_id, "token_hash": token_hash, "expires_at": expires_at},
    )


def find_active_refresh_token(session: Session, token_hash: str) -> RowMapping | None:
    return (
        session.execute(
            text("""
                SELECT id, user_id, token_hash, expires_at, created_at, revoked_at
                FROM refresh_tokens
                WHERE token_hash = :token_hash
                  AND (revoked_at IS NULL OR revoked_at > now() - interval '15 seconds')
                  AND expires_at > now()
            """),
            {"token_hash": token_hash},
        )
        .mappings()
        .one_or_none()
    )


def revoke_refresh_token(session: Session, token_hash: str) -> None:
    session.execute(
        text("""
            UPDATE refresh_tokens
            SET revoked_at = now()
            WHERE token_hash = :token_hash AND revoked_at IS NULL
        """),
        {"token_hash": token_hash},
    )


def revoke_all_user_tokens(session: Session, user_id: int) -> None:
    session.execute(
        text("""
            UPDATE refresh_tokens
            SET revoked_at = now()
            WHERE user_id = :user_id AND revoked_at IS NULL
        """),
        {"user_id": user_id},
    )
