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
    """Format records as JSON while preserving only explicit non-sensitive fields.

    I campi sensibili (token, password, authorization, secret, credentials)
    vengono redatti automaticamente per evitare che finiscano nei log, anche
    quando qualcuno passa un dizionario di extra-fields con dati riservati.
    """

    _SENSITIVE_KEYS = {"token", "access_token", "refresh_token", "password", "password_hash", "secret", "authorization", "credentials", "api_key", "client_secret", "firebase_credentials_file"}

    def _redact(self, value: Any) -> Any:
        if isinstance(value, str):
            if len(value) > 8:
                return value[:3] + "***" + value[-2:]
            return "***"
        return value

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
            if key.lower() in self._SENSITIVE_KEYS:
                value = self._redact(value)
            log_data[key] = value
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False, default=str)


def get_logger(name: str) -> logging.Logger:
    """Return a standard logger; callers decide which non-sensitive fields to add."""
    return logging.getLogger(name)
