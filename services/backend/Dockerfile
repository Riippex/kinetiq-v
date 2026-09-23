# Stage 1: Build virtualenv using uv
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.6.5 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies without installing the project itself
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install project
COPY src/ ./src/
COPY manage.py ./
RUN uv sync --frozen --no-dev

# Stage 2: Minimal runtime image
FROM python:3.12-slim AS runner

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create non-root user
RUN groupadd -g 1001 appuser && \
    useradd -u 1001 -g appuser -s /bin/sh -m appuser

# Copy virtualenv and application code
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/manage.py /app/manage.py

USER appuser

EXPOSE 8000

CMD ["uvicorn", "kinetiq.bootstrap.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--lifespan", "on"]
