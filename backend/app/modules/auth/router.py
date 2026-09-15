"""Authentication endpoints: login, token refresh, and logout."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.auth import service
from app.modules.auth.schemas import (
    LoginRequest,
    RefreshTokenRequest,
    TokenResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, session: DatabaseSession) -> TokenResponse:
    """Вход пользователя в систему по логину и паролю. Возвращает access и refresh токены."""
    try:
        return service.authenticate_user(session, data.username, data.password)
    except service.InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(data: RefreshTokenRequest, session: DatabaseSession) -> TokenResponse:
    """Обновление access-токена с ротацией refresh-токена."""
    try:
        return service.refresh_access_token(session, data.refresh_token)
    except service.InvalidTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или отозванный refresh-токен",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


@router.post("/logout")
def logout(data: RefreshTokenRequest, session: DatabaseSession) -> dict[str, str]:
    """Выход из системы и отзыв действующего refresh-токена."""
    service.logout_user(session, data.refresh_token)
    return {"status": "ok"}
