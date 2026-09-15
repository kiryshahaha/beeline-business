"""Finite authentication protocol values."""

from enum import StrEnum


class TokenType(StrEnum):
    BEARER = "bearer"
