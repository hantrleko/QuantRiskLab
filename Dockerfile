FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist ./frontend/dist
COPY data/quantrisklab.duckdb ./data/quantrisklab.duckdb
EXPOSE 8080
CMD ["sh", "-c", "uv run uvicorn quantrisklab.api.app:app --host 0.0.0.0 --port ${PORT:-8080}"]