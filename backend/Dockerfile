ARG PYTHON_IMAGE=python:3.11.13-slim-bookworm
FROM ${PYTHON_IMAGE}

ARG APP_VERSION=0.3.20
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown
ARG RELEASE_SOURCE_SHA256=unknown
ARG MCP_SOURCE_SHA256=unknown
ARG MCP_BINARY_SHA256=unknown

LABEL org.opencontainers.image.version=${APP_VERSION} \
      org.opencontainers.image.revision=${GIT_COMMIT} \
      org.opencontainers.image.created=${BUILD_TIME} \
      com.ztqc.release.source-sha256=${RELEASE_SOURCE_SHA256} \
      com.ztqc.mcp.source-sha256=${MCP_SOURCE_SHA256} \
      com.ztqc.mcp.binary-sha256=${MCP_BINARY_SHA256}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION} \
    GIT_COMMIT=${GIT_COMMIT} \
    BUILD_TIME=${BUILD_TIME} \
    RELEASE_SOURCE_SHA256=${RELEASE_SOURCE_SHA256} \
    MCP_SOURCE_SHA256=${MCP_SOURCE_SHA256} \
    MCP_BINARY_SHA256=${MCP_BINARY_SHA256}

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir \
    --extra-index-url https://mirrors.aliyun.com/pypi/simple/ \
    .

COPY app /app/app
COPY alembic.ini /app/alembic.ini
COPY bin /app/bin

ENV PYTHONPATH=/app

RUN if [ -f /app/bin/xiaohongshu-mcp ]; then \
      python -c "from pathlib import Path; data = Path('/app/bin/xiaohongshu-mcp').read_bytes(); assert data[:4] == b'\x7fELF' and data[4] == 2 and int.from_bytes(data[18:20], 'little') == 62, 'xiaohongshu-mcp must be a Linux x86_64 ELF binary'"; \
      chmod +x /app/bin/xiaohongshu-mcp; \
    fi

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
