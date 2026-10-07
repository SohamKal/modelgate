"""An allowlist keeps content and credentials out of request logs."""

import json
import logging
import sys
from datetime import UTC, datetime

SAFE_FIELDS = (
    "request_id",
    "status_code",
    "duration_ms",
    "release_name",
    "serving_role",
    "config_version",
    "recording_status",
)


class SafeJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": "modelgate",
            "event": record.msg
            if record.msg in {"request_complete", "recording_degraded"}
            else "request_complete",
        }
        for field in SAFE_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload)


def configure_logging() -> None:
    logger = logging.getLogger("modelgate")
    if not any(isinstance(handler.formatter, SafeJsonFormatter) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(SafeJsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # HTTPX request URLs are not part of our safe log contract.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
