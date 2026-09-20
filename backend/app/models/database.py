"""Async SQLAlchemy engine/session plumbing (Phase 3, docs/database-schema.md).

`DATABASE_URL` selects the backend. When unset (the default for dev/tests),
`Settings.effective_database_url` falls back to an in-memory sqlite database
via the `aiosqlite` driver: it speaks the same SQLAlchemy async API as
Postgres, needs no external service, and is fast enough to run in every test.
Production deployments set `DATABASE_URL=postgresql+psycopg://...` and get
the exact same repository code path — nothing in `app/services/
session_repository.py` branches on which backend is active.

sqlite's in-memory database only exists for the lifetime of one connection,
so a sqlite engine is built with `StaticPool` (a single shared connection)
rather than SQLAlchemy's normal pooling, which would open a *new*, empty
in-memory database per checkout.

Postgres uses `NullPool` rather than SQLAlchemy's default `QueuePool`: many
call sites (each test module, `SessionRepository`, `JobRunner`) construct
their own short-lived engine, and several test files never call `.dispose()`
on it. With `QueuePool`'s default of 5 pooled + 10 overflow connections held
open per undisposed engine, a couple hundred tests against a real Postgres
(`max_connections` defaults to 100) exhausts the server's connection limit —
this was a genuine bug hit the first time this project's test suite ran
against real Postgres (docker-compose Postgres is a single-instance service
container in CI, not a per-test schema). `NullPool` opens a physical
connection per checkout and closes it immediately on release, so an
undisposed engine has zero idle connections left behind.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool, StaticPool


class Base(DeclarativeBase):
    """Shared declarative base for every Phase 3 ORM model."""


def create_engine_for_url(database_url: str) -> AsyncEngine:
    if database_url.startswith("sqlite"):
        return create_async_engine(
            database_url,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    return create_async_engine(database_url, poolclass=NullPool)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_models(engine: AsyncEngine) -> None:
    """Create every table if it does not already exist. Used for the sqlite
    test/dev path; a real Postgres deployment applies `backend/alembic/`
    migrations instead (see `backend/alembic/README` / CHANGELOG)."""
    # Import inside the function, not at module scope, so importing
    # `database.py` alone never pulls in every ORM model transitively.
    from app.models import orm  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
