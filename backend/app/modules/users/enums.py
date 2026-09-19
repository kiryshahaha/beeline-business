"""Domain enumeration for user roles."""

from enum import StrEnum


class UserRole(StrEnum):
    OBSERVER = "observer"
    FOREMAN = "foreman"
    WORKER = "worker"


class TransportType(StrEnum):
    CAR = "car"
    WALKING = "walking"
    BICYCLE = "bicycle"
    PUBLIC_TRANSPORT = "public_transport"
