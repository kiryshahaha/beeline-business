"""Client-visible report refusals; the router turns them into HTTP errors."""

from typing import Any


class ReportError(Exception):
    """A refusal with a stable code, a short Russian message and the related values."""

    def __init__(self, status: int, code: str, message: str, **details: Any):
        super().__init__(message)
        self.status = status
        self.detail = {"code": code, "message": message, **details}
