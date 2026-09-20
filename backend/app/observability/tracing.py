"""OpenTelemetry setup (brief §15).

`configure_tracing()` installs a process-wide `TracerProvider` with either a
console exporter (default — zero extra infra, spans print as JSON-ish lines
to stdout) or an OTLP exporter (`OTEL_EXPORTER=otlp`, pointed at
`OTEL_EXPORTER_OTLP_ENDPOINT`) for a real collector. It is safe to call more
than once (idempotent) and safe to never call at all: `start_span()` falls
back to the global no-op tracer OpenTelemetry provides by default, so
importing/using this module never requires the `opentelemetry-sdk` exporter
pipeline to be configured — matches every other lazy-init provider seam in
this codebase.

`start_span()` is the one context manager agent/job-runner code opens a span
with; `app/agents/_common.py`'s `timed_run()` calls it internally so callers
get one span per agent run without duplicating span bookkeeping at every call
site.
"""

from __future__ import annotations

import typing
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

if typing.TYPE_CHECKING:
    from app.config.settings import Settings

_TRACER_NAME = "multi-agent-research-system"
_configured = False


def configure_tracing(settings: Settings | None = None) -> None:
    """Install the process-wide `TracerProvider`. Idempotent: a second call
    (e.g. from a test fixture that also imports `main`) is a no-op so spans
    never end up exported twice."""
    global _configured
    if _configured:
        return

    if settings is None:
        from app.config.settings import get_settings

        settings = get_settings()

    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.app_name})
    )

    if settings.otel_exporter == "otlp":
        # Imported lazily: the OTLP exporter package is an optional extra
        # infra dependency, and constructing it opens no connection until a
        # span is actually exported — same lazy-init rule as every provider.
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _configured = True


@contextmanager
def start_span(name: str, attributes: dict[str, object] | None = None) -> Iterator[trace.Span]:
    """Open one span covering the `with` block. Works whether or not
    `configure_tracing()` has run — OpenTelemetry's default global tracer
    provider is a documented no-op, so this is always safe to call (e.g.
    from unit tests that never touch `app/main.py`)."""
    tracer = trace.get_tracer(_TRACER_NAME)
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                # `attributes` is intentionally the caller-friendly
                # `dict[str, object]`, wider than OTel's actual
                # `AttributeValue` union — callers only ever pass OTel-valid
                # primitives in practice (see `_common.py`'s call sites).
                span.set_attribute(key, value)  # type: ignore[arg-type]
        yield span


def record_span(
    name: str,
    *,
    start_time_ns: int,
    end_time_ns: int,
    attributes: dict[str, object] | None = None,
) -> None:
    """Record one already-finished span with accurate historical timing.

    `app/agents/_common.py`'s `timed_run()` only knows the agent's name once
    the caller builds `AgentRunMeta` at the *end* of the timed block, so it
    can't wrap the work in `start_span()`'s `with` statement without
    restructuring every agent module. This reconstructs the span after the
    fact instead, using OTel's `start_time`/`end_time` span arguments so the
    exported span still reflects the real duration rather than collapsing to
    zero.
    """
    tracer = trace.get_tracer(_TRACER_NAME)
    span = tracer.start_span(
        name, start_time=start_time_ns, attributes=attributes or {}  # type: ignore[arg-type]
    )
    span.end(end_time=end_time_ns)
