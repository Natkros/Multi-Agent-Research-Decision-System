#!/bin/sh
# Runs migrations before the app starts so every container boot (including a
# fresh `docker compose up`) ends with the schema at `head` — never relies on
# someone remembering a manual `alembic upgrade` step. Only migrates when a
# real DATABASE_URL is configured; the sqlite in-memory fallback has no
# durable schema to migrate.
set -e

if [ -n "$DATABASE_URL" ]; then
    echo "entrypoint: running alembic upgrade head"
    alembic upgrade head
else
    echo "entrypoint: DATABASE_URL unset, skipping migrations (in-memory sqlite fallback)"
fi

exec "$@"
