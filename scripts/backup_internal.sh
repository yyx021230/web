#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${ROOT_DIR}/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

cd "$ROOT_DIR"

echo "[1/2] 备份 PostgreSQL..."
docker compose -f docker-compose.internal.yml exec -T postgres sh -lc \
  'pg_dump -U "${POSTGRES_USER:-ai_user}" "${POSTGRES_DB:-ai_creative}"' \
  > "${BACKUP_DIR}/postgres.sql"

echo "[2/2] 备份 uploads..."
tar -czf "${BACKUP_DIR}/uploads.tar.gz" -C "${ROOT_DIR}/data" uploads

echo "备份完成: ${BACKUP_DIR}"
