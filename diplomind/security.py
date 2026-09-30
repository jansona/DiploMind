"""Small transport safeguards for bearer-token room sessions."""
from __future__ import annotations

import logging
import re

_SECRET_QUERY = re.compile(r"(?i)([?&](?:token|api_key|passcode)=)[^&\s\"']*")


class RedactAccessTokens(logging.Filter):
    """Uvicorn receives complete URLs, including EventSource query credentials."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_SECRET_QUERY.sub(r"\1[REDACTED]", arg) if isinstance(arg, str) else arg
                                for arg in record.args)
        if isinstance(record.msg, str):
            record.msg = _SECRET_QUERY.sub(r"\1[REDACTED]", record.msg)
        return True


def install_access_log_redaction() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactAccessTokens) for f in logger.filters):
        logger.addFilter(RedactAccessTokens())


async def private_api_headers(request, call_next):
    response = await call_next(request)
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response
