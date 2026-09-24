"""Authentication service: login, token issuance, token rotation, and logout."""

import jwt
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
    verify_password,
)
from app.modules.auth import repository
from app.modules.auth.enums import TokenType
from app.modules.auth.schemas import TokenResponse
from app.modules.users import repository as users_repository


class InvalidCredentialsError(Exception):
    pass


class InvalidTokenError(Exception):
    pass


def authenticate_user(session: Session, username: str, password: str) -> TokenResponse:
    with session.begin():
        user = users_repository.find_user_by_username(session, username)
        if user is None or not verify_password(password, user["password_hash"]):
            raise InvalidCredentialsError

        settings = get_settings()
        payload = {
            "sub": str(user["id"]),
            "username": user["username"],
            "role": user["role"],
        }
        access_token = create_access_token(payload)
        refresh_token, expires_at = create_refresh_token(payload)

        repository.add_refresh_token(
            session,
            user_id=user["id"],
            token_hash=hash_token(refresh_token),
            expires_at=expires_at,
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=TokenType.BEARER,
            expires_in=settings.jwt_access_token_expire_minutes * 60,
        )


def refresh_access_token(session: Session, raw_token: str) -> TokenResponse:
    try:
        payload = decode_token(raw_token)
        if payload.get("type") != "refresh":
            raise InvalidTokenError
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as error:
        raise InvalidTokenError from error

    with session.begin():
        token_hash = hash_token(raw_token)
        consumed_record = repository.consume_active_refresh_token(session, token_hash, user_id)
        if consumed_record is None:
            raise InvalidTokenError

        user = users_repository.find_user_by_id(session, user_id)
        if user is None:
            raise InvalidTokenError

        settings = get_settings()
        token_payload = {
            "sub": str(user["id"]),
            "username": user["username"],
            "role": user["role"],
        }
        new_access_token = create_access_token(token_payload)
        new_refresh_token, expires_at = create_refresh_token(token_payload)

        repository.add_refresh_token(
            session,
            user_id=user["id"],
            token_hash=hash_token(new_refresh_token),
            expires_at=expires_at,
        )

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type=TokenType.BEARER,
            expires_in=settings.jwt_access_token_expire_minutes * 60,
        )


def logout_user(session: Session, raw_token: str) -> None:
    with session.begin():
        token_hash = hash_token(raw_token)
        repository.revoke_refresh_token(session, token_hash)
