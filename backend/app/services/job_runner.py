"""Lightweight async job execution (Phase 6, brief §6: "Celery/Redis OR
lightweight async job architecture for MVP" — research runs are long,
multi-minute, many-LLM-call jobs that must survive an API process restart
and be independently retryable).

Celery was skipped for now: every phase of this codebase has stayed
dependency-light and fully offline-testable (no broker, no separate worker
deploy target needed to run the test suite or a local dev server), and the
actual requirement — durable job state, recovery after a crash, bounded
concurrency — doesn't need a message broker to satisfy. `JobStore`/
`JobHandler` are the seam: a `CeleryJobStore` implementing the same
`JobStore` ABC (backed by Celery's result backend) would let `JobRunner`'s
scheduling logic and every caller (`app/api/research.py`, `app/main.py`)
stay untouched if Celery is ever warranted.

Durability + recovery: every job is a row in the `jobs` table
(`app/models/orm.py::JobORM`). `JobRunner.start()` is idempotent and, on
first call, requeues every `pending`/`running` row it finds — a `running`
row means the *previous* process died mid-job, so it gets resumed rather
than silently orphaned. `start()` is also called lazily from `enqueue()` so
job processing works even under a test harness (see `app/main.py`'s comment
about ASGI test transports) that never drives FastAPI's lifespan events.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select

from app.config.settings import Settings, get_settings
from app.models.database import create_engine_for_url, init_models, make_sessionmaker
from app.models.orm import JobORM
from app.observability.logging import log_event
from app.observability.tracing import start_span

JobStatus = Literal["pending", "running", "completed", "failed"]


class JobRecord(BaseModel):
    id: UUID
    job_type: str
    payload: dict
    status: JobStatus
    attempts: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class JobStore(ABC):
    """Durable job persistence seam. See module docstring: a `CeleryJobStore`
    implementing this same interface is the documented upgrade path."""

    @abstractmethod
    async def create(self, job_type: str, payload: dict) -> JobRecord:
        raise NotImplementedError

    @abstractmethod
    async def get(self, job_id: UUID) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def list_recoverable(self) -> list[JobRecord]:
        """Every `pending`/`running` job, oldest first — what `start()`
        requeues on process startup."""
        raise NotImplementedError

    @abstractmethod
    async def mark_running(self, job_id: UUID) -> None:
        raise NotImplementedError

    @abstractmethod
    async def mark_completed(self, job_id: UUID) -> None:
        raise NotImplementedError

    @abstractmethod
    async def mark_failed(self, job_id: UUID, error: str) -> None:
        raise NotImplementedError


class PostgresJobStore(JobStore):
    """Same lazy-init-tables pattern as `SessionRepository`: constructing
    this never opens a connection, and `sqlite+aiosqlite:///:memory:`
    (the default effective database URL) works exactly like a real Postgres
    URL from the caller's point of view."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._engine = create_engine_for_url(self._settings.effective_database_url)
        self._sessionmaker = make_sessionmaker(self._engine)
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if not self._initialized:
                await init_models(self._engine)
                self._initialized = True

    @staticmethod
    def _to_record(row: JobORM) -> JobRecord:
        return JobRecord(
            id=row.id,
            job_type=row.job_type,
            payload=row.payload,
            status=row.status,  # type: ignore[arg-type]
            attempts=row.attempts,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            error=row.error,
        )

    async def create(self, job_type: str, payload: dict) -> JobRecord:
        await self._ensure_initialized()
        async with self._sessionmaker() as db:
            row = JobORM(
                id=uuid4(),
                job_type=job_type,
                payload=payload,
                status="pending",
                attempts=0,
                created_at=datetime.now(UTC),
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return self._to_record(row)

    async def get(self, job_id: UUID) -> JobRecord | None:
        await self._ensure_initialized()
        async with self._sessionmaker() as db:
            row = await db.get(JobORM, job_id)
            return self._to_record(row) if row is not None else None

    async def list_recoverable(self) -> list[JobRecord]:
        await self._ensure_initialized()
        async with self._sessionmaker() as db:
            rows = (
                await db.execute(
                    select(JobORM)
                    .where(JobORM.status.in_(["pending", "running"]))
                    .order_by(JobORM.created_at)
                )
            ).scalars().all()
            return [self._to_record(row) for row in rows]

    async def mark_running(self, job_id: UUID) -> None:
        await self._update(job_id, status="running", started_at=datetime.now(UTC), bump_attempts=True)

    async def mark_completed(self, job_id: UUID) -> None:
        await self._update(job_id, status="completed", completed_at=datetime.now(UTC))

    async def mark_failed(self, job_id: UUID, error: str) -> None:
        await self._update(job_id, status="failed", completed_at=datetime.now(UTC), error=error)

    async def _update(
        self,
        job_id: UUID,
        *,
        status: str,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error: str | None = None,
        bump_attempts: bool = False,
    ) -> None:
        await self._ensure_initialized()
        async with self._sessionmaker() as db:
            row = await db.get(JobORM, job_id)
            if row is None:
                return
            row.status = status
            if started_at is not None:
                row.started_at = started_at
            if completed_at is not None:
                row.completed_at = completed_at
            if error is not None:
                row.error = error
            if bump_attempts:
                row.attempts += 1
            await db.commit()

    async def dispose(self) -> None:
        await self._engine.dispose()


JobHandler = Callable[[JobRecord], Awaitable[None]]

_STOP = None  # sentinel pushed onto the queue to end the dispatcher loop


class JobRunner:
    """Bounded-concurrency asyncio worker pool over a durable `JobStore`.

    `start()`'s recovery pass plus every job running under
    `self._semaphore` is what makes "survive an API process restart" and
    "bounded concurrency" both true without a broker: the in-process
    `asyncio.Queue`/`Semaphore` here are pure execution machinery, not
    business state — every state transition a job goes through is persisted
    to `self._store` before/after it happens, so a fresh `JobRunner` built
    against the same store after a crash sees exactly where things stood.
    """

    def __init__(self, store: JobStore, handler: JobHandler, *, concurrency: int = 4) -> None:
        self._store = store
        self._handler = handler
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._queue: asyncio.Queue[UUID | None] = asyncio.Queue()
        self._tasks: set[asyncio.Task] = set()
        self._dispatcher_task: asyncio.Task | None = None
        self._started = False
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        """Idempotent. Recovers `pending`/`running` jobs, then starts the
        dispatcher loop that turns queued job ids into bounded worker
        tasks."""
        if self._started:
            return
        async with self._start_lock:
            if self._started:
                return
            self._dispatcher_task = asyncio.create_task(self._dispatch_loop())
            recoverable = await self._store.list_recoverable()
            for job in recoverable:
                log_event(
                    "app.job_runner",
                    event="job_recovered",
                    status=job.status,
                    job_id=str(job.id),
                    job_type=job.job_type,
                    attempts=job.attempts,
                )
                await self._queue.put(job.id)
            self._started = True

    async def stop(self) -> None:
        """Stop accepting new work and cancel whatever's still in flight.
        A cancelled job's row is left exactly as `mark_running` last wrote
        it — `start()`'s recovery pass on the next process picks it back up,
        the same path a real crash goes through, so shutdown doesn't need
        its own separate "give up gracefully" bookkeeping."""
        if not self._started:
            return
        await self._queue.put(_STOP)
        if self._dispatcher_task is not None:
            await self._dispatcher_task
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._started = False

    async def enqueue(self, job_type: str, payload: dict) -> UUID:
        await self.start()
        job = await self._store.create(job_type, payload)
        log_event("app.job_runner", event="job_enqueued", status="pending", job_id=str(job.id), job_type=job_type)
        await self._queue.put(job.id)
        return job.id

    async def _dispatch_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            if job_id is _STOP:
                return
            task = asyncio.create_task(self._run_job(job_id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run_job(self, job_id: UUID) -> None:
        async with self._semaphore:
            job = await self._store.get(job_id)
            if job is None or job.status in ("completed",):
                return  # defensive: nothing to do, already terminal or gone

            await self._store.mark_running(job_id)
            log_event(
                "app.job_runner", event="job_started", status="running",
                job_id=str(job_id), job_type=job.job_type,
            )
            with start_span(
                "job_runner.run",
                attributes={"job.id": str(job_id), "job.type": job.job_type},
            ) as span:
                try:
                    await self._handler(job)
                except Exception as exc:  # noqa: BLE001 - bounded: recorded, never re-raised
                    span.set_attribute("job.status", "failed")
                    await self._store.mark_failed(job_id, str(exc))
                    log_event(
                        "app.job_runner", event="job_failed", status="error",
                        job_id=str(job_id), job_type=job.job_type, error=str(exc),
                    )
                    return
                span.set_attribute("job.status", "completed")

            await self._store.mark_completed(job_id)
            log_event(
                "app.job_runner", event="job_completed", status="ok",
                job_id=str(job_id), job_type=job.job_type,
            )
