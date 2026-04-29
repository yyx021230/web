#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/2] 等待数据库服务可用..."
docker compose -f docker-compose.internal.yml exec -T postgres sh -lc 'until pg_isready -U "${POSTGRES_USER:-ai_user}"; do sleep 1; done'

echo "[2/2] 执行 Alembic 迁移..."
docker compose -f docker-compose.internal.yml exec -T backend alembic upgrade head

echo "迁移完成"
