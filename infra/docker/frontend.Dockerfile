# syntax=docker/dockerfile:1
# Three stages: deps (install once, cached) -> builder (next build, standalone
# output) -> runtime (only the standalone server + static assets, non-root).

FROM node:20-slim AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:20-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./
# Build-time API URL: baked into the client bundle (Next.js inlines
# NEXT_PUBLIC_* at build time), override with --build-arg for a non-default
# backend origin.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:20-slim AS runtime
RUN groupadd --system app && useradd --system --gid app --home-dir /app app
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# `output: "standalone"` (frontend/next.config.mjs) traces only the
# node_modules actually used at runtime into .next/standalone, so the
# runtime image needs no `npm install` at all.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

RUN chown -R app:app /app
USER app

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=5 \
    CMD node -e "fetch('http://localhost:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
