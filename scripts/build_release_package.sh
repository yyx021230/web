#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="${1:?usage: build_release_package.sh VERSION [OUTPUT_PATH]}"
commit="$(git -C "$repo_root" rev-parse --short HEAD)"
output="${2:-/tmp/web-${version}-${commit}.tar.gz}"

export COPYFILE_DISABLE=1

tar -czf "$output" \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='.next' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='.mypy_cache' \
  --exclude='.env*' \
  --exclude='.venv' \
  --exclude='uploads' \
  --exclude='runtime' \
  --exclude='*.db*' \
  --exclude='db_backups' \
  --exclude='backups' \
  --exclude='cookies.json' \
  --exclude='cookies-*.json' \
  --exclude='backend/content_tag_*.csv' \
  --exclude='._*' \
  -C "$repo_root" \
  backend frontend scripts docker-compose.yml docker-compose.dev.yml

if tar -tzf "$output" | grep -Eq '(^|/)\._'; then
  echo "release package contains forbidden macOS metadata" >&2
  exit 1
fi

gzip -t "$output"
echo "$output"
