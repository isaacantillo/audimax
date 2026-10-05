# Build context is the repo root (see docker-compose.yml): the frontend stage needs frontend/.

FROM node:25-slim AS frontend
WORKDIR /fe
RUN npm install -g pnpm@11.9.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml* ./
RUN pnpm install --frozen-lockfile
COPY frontend/ .
RUN pnpm exec vite build           # tsc is skipped here: the generated client is committed and checked in CI/dev

FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /code
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY --from=frontend /fe/dist ./dist
ENV PATH="/code/.venv/bin:$PATH"
EXPOSE 8000
CMD ["fastapi", "run", "app/main.py", "--port", "8000", "--proxy-headers"]
