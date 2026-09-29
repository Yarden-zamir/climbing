FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Dependencies first so code changes do not invalidate this layer
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .

ARG GIT_REVISION=""
ENV GIT_REVISION=${GIT_REVISION}

# The socket must be writable by the host Caddy, hence umask 000.
CMD ["sh", "-c", "umask 000 && exec uv run --no-sync uvicorn main:app --uds \"$KITSHN_DEFAULT_SOCKET\" --proxy-headers --forwarded-allow-ips '*'"]
