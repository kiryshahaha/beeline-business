"""Password hashing via Argon2 and JWT tokens generation/verification."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import argon2
import jwt
from argon2 import PasswordHasher

from app.core.config import get_settings

_hasher = PasswordHasher()


def hash_password(plain_password: str) -> str:
    """Compute Argon2 hash of plain text password."""
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify password against Argon2 hash; returns False on mismatch or corrupted hash."""
    try:
        return _hasher.verify(password_hash, plain_password)
    except (
        argon2.exceptions.VerifyMismatchError,
        argon2.exceptions.VerificationError,
        argon2.exceptions.InvalidHashError,
    ):
        return False


def hash_token(token: str) -> str:
    """Compute SHA-256 digest of a token for secure storage in database."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Generate short-lived JWT access token."""
    settings = get_settings()
    to_encode = data.copy()
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes))
    to_encode.update({"exp": expire, "iat": now, "type": "access"})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    data: dict, expires_delta: timedelta | None = None
) -> tuple[str, datetime]:
    """Generate long-lived JWT refresh token with unique jti; returns (token, expires_at)."""
    settings = get_settings()
    to_encode = data.copy()
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(days=settings.jwt_refresh_token_expire_days))
    to_encode.update(
        {
            "exp": expire,
            "iat": now,
            "jti": uuid.uuid4().hex,
            "type": "refresh",
        }
    )
    token = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expire


def decode_token(token: str) -> dict:
    """Decode and validate JWT signature and expiration."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
