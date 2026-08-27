# ─── QMIE Dockerfile ────────────────────────────────────────────────────
# Desk UI (Vite) is built first, then copied into the scanner image so
# https://qmie.onrender.com/ can serve ORBIT as well as /health.
FROM node:22-alpine AS desk
WORKDIR /src
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Same-origin API when FastAPI serves this dist. Do not point at Vercel.
ENV VITE_QMIE_API=
RUN npm run build

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Minimal system deps (curl for healthcheck, ca-certs for HTTPS)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd -m -u 1000 qmie

WORKDIR /app

# Install deps first (better layer caching)
COPY python/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy app
COPY python/ /app/
COPY docker/start.sh /app/start.sh
COPY --from=desk /src/dist /app/desk

# Persistent data dir (mount a volume here)
RUN chmod +x /app/start.sh \
    && mkdir -p /app/data \
    && chown -R qmie:qmie /app
USER qmie

ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD sh -c 'curl -fsS "http://127.0.0.1:${PORT:-8080}/health" || exit 1'

CMD ["/app/start.sh"]
