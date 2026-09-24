"""Authentication endpoints: login, token refresh, and logout."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth import service
from app.modules.auth.schemas import (
    LoginRequest,
    LoginResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
DatabaseSession = Annotated[Session, Depends(get_session)]

REFRESH_COOKIE = "refresh_token"


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, response: Response, session: DatabaseSession) -> LoginResponse:
    """
    Вход по логину и паролю. 
    Возвращает access_token; refresh_token устанавливается в httpOnly cookie.
    """
    try:
        tokens = service.authenticate_user(session, data.username, data.password)
    except service.InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    response.set_cookie(
        key=REFRESH_COOKIE,
        value=tokens.refresh_token,
        httponly=True,
        samesite="strict",
        secure=False,  # поставьте True в продакшене (HTTPS)
        max_age=tokens.expires_in * 2,  # запас: чуть дольше access
    )
    return LoginResponse(
        access_token=tokens.access_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


@router.post("/refresh", response_model=LoginResponse)
def refresh_token(
    response: Response,
    session: DatabaseSession,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> LoginResponse:
    """Обновление access-токена. refresh_token берётся из httpOnly cookie."""
    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh-токен отсутствует",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        tokens = service.refresh_access_token(session, refresh_token)
    except service.InvalidTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или отозванный refresh-токен",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    response.set_cookie(
        key=REFRESH_COOKIE,
        value=tokens.refresh_token,
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=tokens.expires_in * 2,
    )
    return LoginResponse(
        access_token=tokens.access_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


@router.post("/logout")
def logout(
    response: Response,
    session: DatabaseSession,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> dict[str, str]:
    """Выход из системы. Отзывает refresh-токен и сбрасывает cookie."""
    if refresh_token:
        service.logout_user(session, refresh_token)
    response.delete_cookie(key=REFRESH_COOKIE, samesite="strict")
    return {"status": "ok"}
