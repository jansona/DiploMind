import logging

from diplomind.security import RedactAccessTokens, install_access_log_redaction


def test_access_log_redacts_bearer_query_without_changing_request():
    path = "/api/stream/ABCD?token=secret-seat-token&room=ABCD"
    record = logging.LogRecord("uvicorn.access", logging.INFO, "server.py", 1,
                               '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1", "GET", path, "1.1", 200), None)
    assert RedactAccessTokens().filter(record)
    assert "secret-seat-token" not in record.getMessage()
    assert "token=[REDACTED]&room=ABCD" in record.getMessage()
    assert "secret-seat-token" in path


def test_redaction_installation_is_idempotent():
    install_access_log_redaction()
    install_access_log_redaction()
    assert sum(isinstance(f, RedactAccessTokens) for f in logging.getLogger("uvicorn.access").filters) == 1
