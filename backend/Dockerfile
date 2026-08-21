ARG PYTHON_IMAGE=python:3.11.13-slim-bookworm
FROM ${PYTHON_IMAGE}

ARG APP_VERSION=0.3.13
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION} \
    GIT_COMMIT=${GIT_COMMIT} \
    BUILD_TIME=${BUILD_TIME}

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

RUN if [ -f /app/bin/xiaohongshu-mcp ]; then chmod +x /app/bin/xiaohongshu-mcp; fi

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
