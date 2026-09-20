"""Shared helpers for agent modules: timing + `AgentRunMeta` construction.

Not one of the five Phase 2 agents itself — a thin utility so every agent
records observability data the same way instead of duplicating the
start/stop/meta boilerplate five times.

Phase 6: `timed_run()` also opens one OTel span (`agent.<agent_name>` is set
once the caller supplies a name via `t.meta(...)`) and emits one structured
JSON log line per agent run, so every node in the graph is traced/logged the
same way without each agent module calling into `app/observability/`
directly.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from app.observability.logging import log_event
from app.observability.tracing import record_span
from app.schemas.state import AgentRunMeta


@dataclass
class _Timer:
    start_time: datetime
    _monotonic_start: float
    _start_time_ns: int
    tool_calls: list[str]
    errors: list[str]

    def meta(
        self,
        *,
        agent_name: str,
        trace_id: str,
        tokens: int,
        model: str,
        confidence: float | None = None,
    ) -> AgentRunMeta:
        latency_ms = int((time.monotonic() - self._monotonic_start) * 1000)
        # The agent name isn't known until the caller builds `AgentRunMeta`
        # here at the end of the timed block, so the span is reconstructed
        # after the fact (via explicit start/end timestamps) rather than
        # opened as a `with`-block wrapping the work — see `record_span`.
        record_span(
            f"agent.{agent_name}",
            start_time_ns=self._start_time_ns,
            end_time_ns=time.time_ns(),
            attributes={
                "trace_id": trace_id,
                "agent": agent_name,
                "model": model,
                "tokens": tokens,
                "latency_ms": latency_ms,
                "tool_calls": len(self.tool_calls),
                "error_count": len(self.errors),
            },
        )
        status = "error" if self.errors else "ok"
        log_event(
            "app.agents",
            event="agent_run",
            trace_id=trace_id,
            agent=agent_name,
            latency_ms=latency_ms,
            tokens=tokens,
            status=status,
            model=model,
            tool_calls=list(self.tool_calls),
            errors=list(self.errors),
        )
        return AgentRunMeta(
            agent_name=agent_name,
            trace_id=trace_id,
            start_time=self.start_time,
            end_time=datetime.now(UTC),
            latency_ms=latency_ms,
            tokens=tokens,
            model=model,
            tool_calls=list(self.tool_calls),
            errors=list(self.errors),
            confidence=confidence,
        )


@contextmanager
def timed_run() -> Iterator[_Timer]:
    """Usage: `with timed_run() as t: ... t.tool_calls.append("llm.complete")`
    then `t.meta(...)` once the work is done."""
    timer = _Timer(
        start_time=datetime.now(UTC),
        _monotonic_start=time.monotonic(),
        _start_time_ns=time.time_ns(),
        tool_calls=[],
        errors=[],
    )
    yield timer
