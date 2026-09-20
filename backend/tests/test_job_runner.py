from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from app.config.settings import Settings
from app.models.orm import JobORM
from app.services.job_runner import JobRecord, JobRunner, PostgresJobStore


def _settings() -> Settings:
    # Fresh in-memory sqlite per Settings instance would defeat the point of
    # sharing one store across two `PostgresJobStore`s in the recovery test,
    # so tests that need a *shared* backing DB build one `PostgresJobStore`
    # and reuse its engine directly instead of constructing a second store
    # from settings alone (sqlite `:memory:` is per-engine, not per-URL).
    return Settings(database_url=None)


async def _wait_until(predicate, *, timeout_s: float = 5.0, interval_s: float = 0.02) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(interval_s)
    return False


async def test_enqueue_persists_pending_job() -> None:
    store = PostgresJobStore(_settings())

    async def handler(job: JobRecord) -> None:
        await asyncio.sleep(10)  # never completes within the test

    runner = JobRunner(store=store, handler=handler, concurrency=2)
    job_id = await runner.enqueue("noop", {"x": 1})

    # Immediately after enqueue, the row exists and is pending-or-running
    # (the dispatcher may have already picked it up) — never "gone".
    record = await store.get(job_id)
    assert record is not None
    assert record.job_type == "noop"
    assert record.status in ("pending", "running")

    await runner.stop()
    await store.dispose()


async def test_job_runner_marks_job_completed() -> None:
    store = PostgresJobStore(_settings())
    completed_ids: list[str] = []

    async def handler(job: JobRecord) -> None:
        completed_ids.append(str(job.id))

    runner = JobRunner(store=store, handler=handler, concurrency=2)
    job_id = await runner.enqueue("noop", {})

    async def _is_completed() -> bool:
        record = await store.get(job_id)
        return record is not None and record.status == "completed"

    assert await _wait_until(_is_completed)
    assert str(job_id) in completed_ids

    await runner.stop()
    await store.dispose()


async def test_job_runner_marks_job_failed_without_crashing() -> None:
    store = PostgresJobStore(_settings())

    async def handler(job: JobRecord) -> None:
        raise RuntimeError("handler blew up")

    runner = JobRunner(store=store, handler=handler, concurrency=2)
    job_id = await runner.enqueue("noop", {})

    async def _is_failed() -> bool:
        record = await store.get(job_id)
        return record is not None and record.status == "failed"

    assert await _wait_until(_is_failed)
    record = await store.get(job_id)
    assert record is not None
    assert record.error is not None and "handler blew up" in record.error

    await runner.stop()
    await store.dispose()


async def test_job_runner_recovers_a_job_left_running_after_a_simulated_restart() -> None:
    """The key recovery scenario: a previous process died mid-job, leaving a
    `running` row behind. A *new* `JobRunner` built against the same store
    must pick it back up on `start()`, not leave it orphaned forever."""
    store = PostgresJobStore(_settings())

    # Simulate a crash: insert a job directly as "running", bypassing
    # `enqueue()` (which would also start a runner and process it).
    await store._ensure_initialized()  # noqa: SLF001 - test needs the table to exist first
    async with store._sessionmaker() as db:  # noqa: SLF001
        orphaned_id = uuid4()
        db.add(
            JobORM(
                id=orphaned_id,
                job_type="research_run",
                payload={"research_id": "does-not-matter"},
                status="running",
                attempts=1,
                created_at=datetime.now(UTC),
                started_at=datetime.now(UTC),
            )
        )
        await db.commit()

    recovered_job_ids: list[str] = []

    async def handler(job: JobRecord) -> None:
        recovered_job_ids.append(str(job.id))

    # Fresh JobRunner instance — analogous to the API process restarting.
    runner = JobRunner(store=store, handler=handler, concurrency=2)
    await runner.start()

    async def _is_completed() -> bool:
        record = await store.get(orphaned_id)
        return record is not None and record.status == "completed"

    assert await _wait_until(_is_completed)
    assert str(orphaned_id) in recovered_job_ids

    await runner.stop()
    await store.dispose()
