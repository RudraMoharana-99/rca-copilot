FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./

COPY README.md ./

RUN uv sync --frozen --no-dev --no-install-project 

COPY src/ ./src/

RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

WORKDIR /app

RUN useradd -m appuser

COPY --from=builder /app/.venv /app/.venv

COPY src/ ./src/

COPY scenarios/ ./scenarios/

ENV PATH="/app/.venv/bin:$PATH"

USER appuser

EXPOSE 8000

CMD ["uvicorn", "rca_copilot.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
