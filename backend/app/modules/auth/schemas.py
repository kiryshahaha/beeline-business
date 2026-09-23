"""Request and response contracts for authentication."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.auth.enums import TokenType

LOGIN_REQUEST_EXAMPLE = {
    "username": "ivanov_worker",
    "password": "StrongPassword123!",
}

TOKEN_RESPONSE_EXAMPLE = {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 900,
}

REFRESH_TOKEN_REQUEST_EXAMPLE = {
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
}


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [LOGIN_REQUEST_EXAMPLE]}
    )

    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class RefreshTokenRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [REFRESH_TOKEN_REQUEST_EXAMPLE]}
    )

    refresh_token: str = Field(description="Действующий refresh token для обновления сессии")


class TokenResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [TOKEN_RESPONSE_EXAMPLE]})

    access_token: str
    refresh_token: str
    token_type: TokenType = TokenType.BEARER
    expires_in: int = Field(description="Время жизни access-токена в секундах")


LOGIN_RESPONSE_EXAMPLE = {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 900,
}


class LoginResponse(BaseModel):
    """Ответ на /login и /refresh: refresh_token передаётся только через httpOnly cookie."""
    model_config = ConfigDict(json_schema_extra={"examples": [LOGIN_RESPONSE_EXAMPLE]})

    access_token: str
    token_type: TokenType = TokenType.BEARER
    expires_in: int = Field(description="Время жизни access-токена в секундах")
