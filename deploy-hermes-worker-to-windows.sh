#!/usr/bin/env bash
set -euo pipefail

PROJECT="${PROJECT:-/Users/yyx/ztqc/web}"
WIN_USER="${WIN_USER:-1}"
WIN_IP="${WIN_IP:-192.168.10.107}"
WIN_PATH="${WIN_PATH:-C:/projects/web}"
WIN_PS_PATH="${WIN_PATH//\//\\}"
WIN_PASS="${WIN_PASS:-}"

cd "$PROJECT"
VERSION="$(node -p "require('./frontend/package.json').version")"
COMMIT="$(git rev-parse --short=12 HEAD)"
TAG="v${VERSION}"
ARCHIVE_NAME="hermes-worker-${VERSION}-${COMMIT}.zip"
ARCHIVE="/tmp/${ARCHIVE_NAME}"
REMOTE_DIR="${WIN_PATH}/.release/incoming"
REMOTE_ARCHIVE="${REMOTE_DIR}/${ARCHIVE_NAME}"
REMOTE_SCRIPT="${REMOTE_DIR}/Deploy-HermesWorkerRelease.ps1"

if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo "Refusing to deploy a dirty working tree." >&2
  exit 1
fi
if ! git tag --points-at HEAD | grep -Fxq "$TAG"; then
  echo "HEAD must have release tag ${TAG}." >&2
  exit 1
fi

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15)
SCP=(scp -o BatchMode=yes -o ConnectTimeout=15)
if [[ -n "$WIN_PASS" ]]; then
  SSH=(sshpass -p "$WIN_PASS" ssh -o ConnectTimeout=15)
  SCP=(sshpass -p "$WIN_PASS" scp -o ConnectTimeout=15)
fi
TARGET="${WIN_USER}@${WIN_IP}"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/hermes-worker-release.XXXXXX")"
trap 'rm -rf "$STAGE" "$ARCHIVE"' EXIT

git archive --format=tar HEAD \
  ops/xhs_hermes/run_daily_8x5.py \
  scripts/windows/Dockerfile.hermes-worker-release \
  | tar -xf - -C "$STAGE"
(
  cd "$STAGE"
  zip -qr "$ARCHIVE" .
)

"${SSH[@]}" "$TARGET" "powershell -NoProfile -Command \"New-Item -ItemType Directory -Force -Path '${REMOTE_DIR}' | Out-Null\""
"${SCP[@]}" "$ARCHIVE" "${TARGET}:${REMOTE_ARCHIVE}"
"${SCP[@]}" "$PROJECT/scripts/windows/Deploy-HermesWorkerRelease.ps1" "${TARGET}:${REMOTE_SCRIPT}"
"${SSH[@]}" "$TARGET" \
  "powershell -NoProfile -ExecutionPolicy Bypass -Command \"& '${WIN_PS_PATH}\\.release\\incoming\\Deploy-HermesWorkerRelease.ps1' -Version '${VERSION}' -Commit '${COMMIT}' -Archive '${WIN_PS_PATH}\\.release\\incoming\\${ARCHIVE_NAME}' -ProjectRoot '${WIN_PS_PATH}'; if (-not \$?) { exit 1 }\""

"${SSH[@]}" "$TARGET" \
  "powershell -NoProfile -Command \"docker inspect web-hermes-worker-1 --format '{{.Config.Image}}|{{.State.Health.Status}}'\""
