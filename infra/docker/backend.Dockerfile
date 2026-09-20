# syntax=docker/dockerfile:1
# Multi-stage build: `builder` resolves the full dependency set into a venv,
# `runtime` copies only that venv + app source into a slim, non-root image —
# keeps the shipped image free of build toolchains (gcc, headers) that
# sentence-transformers/psycopg[binary] pull in at install time.

FROM python:3.12-slim AS builder

WORKDIR /build

# build-essential: sentence-transformers/tokenizers compile native extensions
# on some platforms; harmless no-op when prebuilt wheels are used.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only dependency manifests first so `pip install` is cached across
# source-only changes.
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && mkdir -p app && touch app/__init__.py \
    && pip install --no-cache-dir .

COPY backend/ ./
RUN pip install --no-cache-dir .

FROM python:3.12-slim AS runtime

# libpq5: runtime shared lib psycopg[binary]'s wheel links against.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app && useradd --system --gid app --home-dir /app app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY infra/docker/backend-entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
