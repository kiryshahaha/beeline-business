"""Domain enumeration for user roles."""

from enum import StrEnum


class UserRole(StrEnum):
    OBSERVER = "observer"
    FOREMAN = "foreman"
    WORKER = "worker"
