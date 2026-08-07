#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
BACKUP_ROOT="${BACKUP_ROOT:-${ROOT_DIR}/../web-backups}"
BACKUP_MIRROR_DIR="${BACKUP_MIRROR_DIR:-}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"

mkdir -p "$BACKUP_DIR"
cd "$ROOT_DIR"

echo "[1/4] Dump PostgreSQL"
docker compose -f "$COMPOSE_FILE" exec -T postgres sh -lc \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "${BACKUP_DIR}/postgres.dump"

echo "[2/4] Validate PostgreSQL dump"
docker compose -f "$COMPOSE_FILE" exec -T postgres pg_restore -l < "${BACKUP_DIR}/postgres.dump" > /dev/null

echo "[3/4] Archive uploads"
UPLOADS_PATH="${UPLOADS_HOST_PATH:-}"
if [[ -z "$UPLOADS_PATH" ]]; then
  BACKEND_CONTAINER="$(docker compose -f "$COMPOSE_FILE" ps --all -q backend 2>/dev/null || true)"
  if [[ -n "$BACKEND_CONTAINER" ]]; then
    UPLOADS_PATH="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/uploads"}}{{.Source}}{{end}}{{end}}' "$BACKEND_CONTAINER" 2>/dev/null || true)"
  fi
fi
UPLOADS_PATH="${UPLOADS_PATH:-${ROOT_DIR}/uploads}"
if [[ "$UPLOADS_PATH" != /* ]]; then
  UPLOADS_PATH="${ROOT_DIR}/${UPLOADS_PATH#./}"
fi
if [[ -d "$UPLOADS_PATH" ]]; then
  tar -czf "${BACKUP_DIR}/uploads.tar.gz" -C "$UPLOADS_PATH" .
fi

cat > "${BACKUP_DIR}/manifest.txt" <<EOF
created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
git_commit=$(git rev-parse HEAD 2>/dev/null || echo unknown)
compose_file=${COMPOSE_FILE}
database_bytes=$(wc -c < "${BACKUP_DIR}/postgres.dump")
EOF

if [[ -n "$BACKUP_MIRROR_DIR" ]]; then
  echo "[4/4] Copy backup to mirror"
  mkdir -p "$BACKUP_MIRROR_DIR"
  cp -R "$BACKUP_DIR" "$BACKUP_MIRROR_DIR/"
else
  echo "[4/4] Mirror disabled; set BACKUP_MIRROR_DIR for an off-host copy"
fi

if [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] && (( RETENTION_DAYS > 0 )); then
  find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" -name '20????????_??????' -exec rm -rf {} +
fi

echo "Backup completed: ${BACKUP_DIR}"
