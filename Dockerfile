# syntax=docker/dockerfile:1

FROM python:3.12.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.10.10 /uv /uvx /bin/

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

RUN addgroup --system runcoach \
    && adduser --system --ingroup runcoach runcoach \
    && mkdir -p /app/data/private \
    && chown -R runcoach:runcoach /app

USER runcoach

EXPOSE 8000

CMD ["uvicorn", "runcoach.main:app", "--host", "0.0.0.0", "--port", "8000"]