"""Redact bearer-like values from URL query strings in HTTP access logs."""

import logging
import re
from collections.abc import Mapping

_SECRET_QUERY_VALUE = re.compile(
    r"([?&](?:access_token|refresh_token|token|authorization)=)[^&\s\"']*",
    re.IGNORECASE,
)


def _redact(value):
    if isinstance(value, str):
        return _SECRET_QUERY_VALUE.sub(r"\1[REDACTED]", value)
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _redact(item) for key, item in value.items()}
    return value


class AccessLogRedactionFilter(logging.Filter):
    """Mask secret query values in structured arguments used by uvicorn.access."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.args = _redact(record.args)
        if isinstance(record.msg, str):
            record.msg = _SECRET_QUERY_VALUE.sub(r"\1[REDACTED]", record.msg)
        return True


def install_access_log_redaction() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, AccessLogRedactionFilter) for item in logger.filters):
        logger.addFilter(AccessLogRedactionFilter())
