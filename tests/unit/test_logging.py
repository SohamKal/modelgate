import logging

from app.core.logging import SafeJsonFormatter


def test_log_formatter_ignores_content_credentials_and_exception_text() -> None:
    record = logging.LogRecord("modelgate", logging.INFO, "test", 1, "private marker", (), None)
    record.request_id = "synthetic-id"
    record.prompt = "private prompt"
    record.authorization = "private credential"
    output = SafeJsonFormatter().format(record)
    assert "synthetic-id" in output
    assert "private" not in output
