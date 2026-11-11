# --- frontend build -----------------------------------------------------------
# No `# syntax=docker/dockerfile:1` directive on purpose: it makes every build
# fetch a frontend image from Docker Hub before doing anything, which fails
# behind registries that only mirror library/* images. Nothing below needs a
# newer frontend than the one BuildKit ships with.
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- runtime: one container serves both API and the built SPA -----------------
# Optional convenience for a single-user local install (NAS, an old laptop, a
# spare box). The primary way to run EasyTravel is still `scripts/dev.ps1` /
# `scripts/dev.sh`, and the security model does not change: no accounts, no
# authentication — keep this on a trusted network and never expose it publicly.
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FASTAPI_API_HOST=0.0.0.0 \
    FASTAPI_API_PORT=8000 \
    DATABASE_PATH=/app/data/easy_travel.sqlite3

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Run unprivileged: nothing here needs root, and a container that can only write
# its own data volume is one less thing to reason about. The dev toolchain
# (pytest, ruff) lives in requirements-dev.txt and is deliberately absent.
RUN useradd --create-home --uid 10001 travel \
    && mkdir -p /app/data \
    && chown -R travel:travel /app
USER travel

VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["python", "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
