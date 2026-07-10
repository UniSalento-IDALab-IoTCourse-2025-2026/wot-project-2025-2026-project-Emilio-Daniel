from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

_STANDARD_LOG_RECORD_KEYS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


def configure_logging(level: str) -> None:
    """Configure JSON logs without secrets or raw health payloads."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))


class JsonLogFormatter(logging.Formatter):
    """Format records as JSON while preserving only explicit non-sensitive fields."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_KEYS or key.startswith("_"):
                continue
            log_data[key] = value
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False, default=str)


def get_logger(name: str) -> logging.Logger:
    """Return a standard logger; callers decide which non-sensitive fields to add."""
    return logging.getLogger(name)
