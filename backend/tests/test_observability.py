from __future__ import annotations

import json
import logging

from app.observability.logging import JsonFormatter, log_event
from app.observability.tracing import record_span, start_span


def test_log_event_emits_parseable_json_with_required_fields() -> None:
    logger_name = "app.test.observability"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    records: list[str] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(self.format(record))

    handler = _CaptureHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    try:
        log_event(
            logger_name,
            event="agent_run",
            trace_id="trace-123",
            agent="researcher",
            latency_ms=42,
            tokens=17,
            status="ok",
        )
    finally:
        logger.removeHandler(handler)

    assert len(records) == 1
    payload = json.loads(records[0])  # must be valid JSON, one line

    # Brief §15's example shape: trace_id, agent, latency_ms, tokens, status.
    assert payload["trace_id"] == "trace-123"
    assert payload["agent"] == "researcher"
    assert payload["latency_ms"] == 42
    assert payload["tokens"] == 17
    assert payload["status"] == "ok"
    assert payload["event"] == "agent_run"
    assert "timestamp" in payload
    assert payload["level"] == "INFO"


def test_log_event_carries_extra_fields() -> None:
    logger_name = "app.test.observability.extra"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    records: list[str] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(self.format(record))

    handler = _CaptureHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    try:
        log_event(logger_name, event="job_started", job_id="abc-123", job_type="research_run")
    finally:
        logger.removeHandler(handler)

    payload = json.loads(records[0])
    assert payload["job_id"] == "abc-123"
    assert payload["job_type"] == "research_run"


def test_start_span_and_record_span_do_not_raise_without_configured_exporter() -> None:
    # `configure_tracing()` is never called by this test — exercises the
    # documented "safe to use with the default no-op provider" behavior.
    with start_span("test.span", attributes={"k": "v"}):
        pass

    record_span("test.recorded_span", start_time_ns=1_000_000, end_time_ns=2_000_000)
