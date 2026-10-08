# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

ARG INSTALL_ML=false

COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=proxy_ca,required=false \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    if [ "$INSTALL_ML" = "true" ]; then \
      uv sync --frozen --no-dev --no-install-project --extra ml; \
    else \
      uv sync --frozen --no-dev --no-install-project; \
    fi

COPY backend/ .
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=proxy_ca,required=false \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    if [ "$INSTALL_ML" = "true" ]; then \
      uv sync --frozen --no-dev --no-editable --extra ml; \
    else \
      uv sync --frozen --no-dev --no-editable; \
    fi

FROM python:3.12-slim-bookworm AS runtime

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RAGOPS_ENVIRONMENT=production
WORKDIR /app

RUN groupadd --gid 10001 ragops \
    && useradd --uid 10001 --gid ragops --create-home --home-dir /home/ragops ragops

COPY --from=builder --chown=ragops:ragops /app /app

USER ragops
EXPOSE 8000

CMD ["uvicorn", "ragops.main:app", "--host", "0.0.0.0", "--port", "8000"]

