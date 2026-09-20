"""Alembic environment (Phase 3). Resolves the migration URL from the same
`Settings.database_url` the app uses at runtime (falling back to
`app.config.settings.get_settings()` when `alembic.ini`/`-x` don't override
it), so migrations and the app never drift onto two different configs.

Migrations always run with a *synchronous* driver (psycopg's sync mode,
even though the app uses SQLAlchemy's async engine at runtime) — Alembic's
autogenerate/offline machinery is sync-only; `_sync_url()` below strips any
`+aiosqlite`/`+asyncpg`-style async suffix from the configured URL.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.models.orm import Base  # noqa: E402  (after sys.path is set up by alembic)

target_metadata = Base.metadata


def _sync_url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    from app.config.settings import get_settings

    url = get_settings().effective_database_url
    return url.replace("+aiosqlite", "").replace("+asyncpg", "").replace("+psycopg_async", "")


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
