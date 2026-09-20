"""Structured JSON logging (brief §15).

`configure_logging()` replaces the root logger's handlers with one that
emits a single JSON object per line — the shape the brief's §15 example
calls for: `trace_id`, `agent`, `latency_ms`, `tokens`, `status`, plus
whatever extra fields a call site passes. Call it once, early (`app/main.py`
does this at import time so it's active for both `uvicorn` and the test
suite).

`log_event()` is the call site API every agent run and job-runner state
transition goes through — a thin wrapper over `logging.Logger` that puts
structured fields where `JsonFormatter` expects them (via `extra`), instead
of hand-building dicts at every call site.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_RESERVED_LOGRECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)

_LOGGER_NAME = "app.observability"


class JsonFormatter(logging.Formatter):
    """Renders one JSON object per log line. Any attribute passed via
    `extra={...}` (and not already a stdlib `LogRecord` field) is included
    verbatim, so `log_event(..., tokens=123, status="ok")` round-trips as
    `{"tokens": 123, "status": "ok", ...}` with no per-field boilerplate here.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_ATTRS or key in payload:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Idempotent: safe to call multiple times (e.g. once from `main.py`,
    once from a test fixture) without stacking duplicate handlers."""
    root = logging.getLogger()
    root.setLevel(level)
    for existing in list(root.handlers):
        root.removeHandler(existing)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


def log_event(
    logger_name: str = _LOGGER_NAME,
    *,
    event: str,
    trace_id: str | None = None,
    agent: str | None = None,
    latency_ms: int | None = None,
    tokens: int | None = None,
    status: str | None = None,
    **extra: Any,
) -> None:
    """Emit one structured JSON log line. `event` is a short machine-readable
    label (`"agent_run"`, `"job_started"`, `"cache_hit"`, ...); the named
    kwargs are the brief §15 example's core fields, always present (as
    `None` when not applicable) so every line has a stable schema, and
    `**extra` carries anything call-site-specific (job id, cache key, ...).
    """
    logger = logging.getLogger(logger_name)
    fields = {
        "event": event,
        "trace_id": trace_id,
        "agent": agent,
        "latency_ms": latency_ms,
        "tokens": tokens,
        "status": status,
        **extra,
    }
    logger.info(event, extra=fields)
