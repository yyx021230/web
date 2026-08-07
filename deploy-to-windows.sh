#!/bin/bash
# deploy-to-windows.sh — 一键部署到 Windows Docker

set -euo pipefail

PROJECT="/Users/yyx/ztqc/web"
MCP_PROJECT="/Users/yyx/ztqc/cc_kaiyuan/claude-code-main/xiaohongshu-mcp-patched"
MCP_BIN_TARGET="/Users/yyx/ztqc/web/backend/bin/xiaohongshu-mcp"
WIN_USER="${WIN_USER:-1}"
WIN_PASS="${WIN_PASS:?Set WIN_PASS before running this script}"
WIN_IP="${WIN_IP:-192.168.10.107}"
WIN_PATH="${WIN_PATH:-C:/projects/web}"
TARBALL="/tmp/web-deploy.tar.gz"

echo "=== 1. 编译 xiaohongshu-mcp (linux/amd64) ==="
cd "$MCP_PROJECT"
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o "$MCP_BIN_TARGET" .

echo "=== 2. 打包代码 ==="
cd "$PROJECT"
rm -f "$TARBALL"
COPYFILE_DISABLE=1 tar czf "$TARBALL" \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='.next' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='.mypy_cache' \
  --exclude='.env*' \
  --exclude='.venv' \
  --exclude='backend/dev.db*' \
  --exclude='backend/*.db' \
  --exclude='backend/*.db-*' \
  --exclude='backend/db_backups' \
  --exclude='backend/uploads' \
  --exclude='backend/content_tag_*.csv' \
  --exclude='backend/test*.db' \
  --exclude='.DS_Store' \
  --exclude='._*' \
  backend/ frontend/ docker-compose.yml

echo "=== 3. 传输到 Windows ==="
sshpass -p "$WIN_PASS" scp "$TARBALL" "${WIN_USER}@${WIN_IP}:${WIN_PATH}/web-deploy.tar.gz"

echo "=== 4. 解压 + 清理 macOS 脏文件 + 重建启动 ==="
sshpass -p "$WIN_PASS" ssh "${WIN_USER}@${WIN_IP}" \
  "cd ${WIN_PATH} && tar xzf web-deploy.tar.gz && powershell -NoProfile -Command \"Get-ChildItem -Path 'C:\projects\web' -Recurse -Force -Filter '._*' | Remove-Item -Force\" && docker compose up -d --build backend frontend ai-worker"

echo "=== 5. 执行数据库迁移 ==="
sshpass -p "$WIN_PASS" ssh "${WIN_USER}@${WIN_IP}" \
  "cd ${WIN_PATH} && docker compose exec -T backend sh -lc \"find /app -name '._*' -type f -delete && python -m alembic upgrade heads\""

echo "=== 6. 查看服务状态 ==="
sshpass -p "$WIN_PASS" ssh "${WIN_USER}@${WIN_IP}" \
  "cd ${WIN_PATH} && docker compose ps backend frontend ai-worker"
