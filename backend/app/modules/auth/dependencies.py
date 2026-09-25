"""FastAPI dependencies for JWT authentication and role-based access control."""

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_session
from app.modules.users import service as users_service
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserRead

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="BearerAuth")
DatabaseSession = Annotated[Session, Depends(get_session)]


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    session: DatabaseSession,
) -> UserRead:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Недействительный или просроченный токен авторизации",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise credentials_exception

    token = credentials.credentials
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise credentials_exception
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as error:
        raise credentials_exception from error

    try:
        # Finish the authentication read before the endpoint starts its write transaction.
        with session.begin():
            user = users_service.get_user(session, user_id)
    except users_service.UserNotFoundError as error:
        raise credentials_exception from error
    # An archived account keeps its history but a still valid access token opens nothing.
    if user.archived_at is not None:
        raise credentials_exception
    return user


def require_roles(*allowed_roles: UserRole) -> Callable[[UserRead], UserRead]:
    def check_role(
        current_user: Annotated[UserRead, Depends(get_current_user)],
    ) -> UserRead:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для выполнения операции",
            )
        return current_user

    return check_role
