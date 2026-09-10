ARG PYTHON_IMAGE=python:3.11.13-slim-bookworm@sha256:86adf8dbadc3d6e82ee5dd2c74bec2e1c2467cdad47886280501df722372d2e1
FROM ${PYTHON_IMAGE}
ARG HERMES_COMMIT=29112bef099274229cadff79cdff7bf7b99c4b77
ARG DEBIAN_MIRROR=https://deb.debian.org
LABEL org.opencontainers.image.title="Hermes XHS production worker" \
      org.opencontainers.image.hermes-revision=${HERMES_COMMIT}

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 HERMES_OCR_BACKEND=rapidocr \
    HERMES_REPO=/opt/hermes-agent HERMES_PYTHON=/opt/venv/bin/python PYTHONPATH=/opt/hermes-agent \
    HERMES_MAX_TEXT_WORKERS=2 HERMES_MAX_IMAGE_WORKERS=5 HERMES_OCR_THREADS=2 \
    HERMES_HOME=/app/web/ops/xhs_hermes/hermes_home \
    PATH=/opt/venv/bin:$PATH TZ=Asia/Shanghai

RUN sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=2 -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::Retries=2 -o Acquire::https::Timeout=30 install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/venv
COPY requirements-linux.lock /tmp/requirements-linux.lock
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements-linux.lock \
    && python -m pip check

COPY hermes-agent /opt/hermes-agent
COPY web /app/web
COPY seed /opt/hermes-seed
WORKDIR /app/web/ops/xhs_hermes
RUN python -c "from run_agent import AIAgent" && python ocr_backend.py
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "container_entrypoint.py", "health"]
ENTRYPOINT ["python", "container_entrypoint.py"]
CMD ["worker"]
