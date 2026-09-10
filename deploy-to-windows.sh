#!/usr/bin/env bash
# Build and deploy a versioned release to the Windows Docker host.

set -euo pipefail

PROJECT="${PROJECT:-/Users/yyx/ztqc/web}"
MCP_PROJECT="${MCP_PROJECT:-/Users/yyx/ztqc/cc_kaiyuan/claude-code-main/xiaohongshu-mcp-patched}"
MCP_BIN_TARGET="${PROJECT}/backend/bin/xiaohongshu-mcp"
WIN_USER="${WIN_USER:-1}"
WIN_IP="${WIN_IP:-192.168.10.107}"
WIN_PATH="${WIN_PATH:-C:/projects/web}"
WIN_PS_PATH="${WIN_PATH//\//\\}"
WIN_PASS="${WIN_PASS:-}"
EXISTING_BACKUP_DIR="${EXISTING_BACKUP_DIR:-}"
GO_TOOLCHAIN="${GO_TOOLCHAIN:-go1.24.6}"

cd "$PROJECT"
PACKAGE_VERSION="$(node -p "require('./frontend/package.json').version")"
VERSION="${APP_VERSION:-$PACKAGE_VERSION}"
COMMIT="$(git rev-parse --short=12 HEAD)"
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
MCP_SOURCE_SHA256="$(
  cd "$MCP_PROJECT"
  find . -type f ! -name 'xiaohongshu-mcp' ! -path './.git/*' -print0 \
    | LC_ALL=C sort -z \
    | xargs -0 shasum -a 256 \
    | shasum -a 256 \
    | awk '{print $1}'
)"
RELEASE_TAG="v${VERSION}"
PACKAGE_NAME="web-${VERSION}-${COMMIT}.tar.gz"
TARBALL="/tmp/${PACKAGE_NAME}"
REMOTE_INCOMING="${WIN_PATH}/.release/incoming"
REMOTE_SCRIPT_DIR="${REMOTE_INCOMING}/scripts"
REMOTE_PACKAGE="${REMOTE_INCOMING}/${PACKAGE_NAME}"
REMOTE_PS_PACKAGE="${WIN_PS_PATH}\\.release\\incoming\\${PACKAGE_NAME}"
REMOTE_PS_DEPLOY_SCRIPT="${WIN_PS_PATH}\\.release\\incoming\\scripts\\Deploy-Release.ps1"
RELEASE_STAGE="$(mktemp -d "${TMPDIR:-/tmp}/web-release-stage.XXXXXX")"
SOURCE_ARCHIVE="${RELEASE_STAGE}/tracked-source.tar.gz"

cleanup() {
  rm -rf "$RELEASE_STAGE"
}
trap cleanup EXIT

if [[ "$VERSION" != "$PACKAGE_VERSION" ]]; then
  echo "APP_VERSION ${VERSION} does not match frontend/package.json ${PACKAGE_VERSION}." >&2
  exit 1
fi

if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo "Refusing to deploy a dirty working tree. Commit the complete release first." >&2
  exit 1
fi

if ! git tag --points-at HEAD | grep -Fxq "$RELEASE_TAG"; then
  echo "HEAD must have release tag ${RELEASE_TAG} before production deployment." >&2
  exit 1
fi

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15)
SCP=(scp -o BatchMode=yes -o ConnectTimeout=15)
if [[ -n "$WIN_PASS" ]]; then
  SSH=(sshpass -p "$WIN_PASS" ssh -o ConnectTimeout=15)
  SCP=(sshpass -p "$WIN_PASS" scp -o ConnectTimeout=15)
fi
TARGET="${WIN_USER}@${WIN_IP}"

echo "[1/6] Build xiaohongshu-mcp for linux/amd64"
cd "$MCP_PROJECT"
GOTOOLCHAIN="$GO_TOOLCHAIN" CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o "$MCP_BIN_TARGET" .
MCP_BINARY_SHA256="$(shasum -a 256 "$MCP_BIN_TARGET" | awk '{print $1}')"

echo "[2/6] Create release package ${PACKAGE_NAME}"
cd "$PROJECT"
rm -f "$TARBALL"
git archive --format=tar.gz --output="$SOURCE_ARCHIVE" HEAD \
  backend frontend scripts docker-compose.yml docker-compose.dev.yml README.md
tar xzf "$SOURCE_ARCHIVE" -C "$RELEASE_STAGE"
mkdir -p "$RELEASE_STAGE/backend/bin"
cp "$MCP_BIN_TARGET" "$RELEASE_STAGE/backend/bin/xiaohongshu-mcp"
rm -f "$SOURCE_ARCHIVE"
COPYFILE_DISABLE=1 tar czf "$TARBALL" -C "$RELEASE_STAGE" .

echo "[3/6] Prepare remote release directories"
"${SSH[@]}" "$TARGET" "powershell -NoProfile -Command \"New-Item -ItemType Directory -Force -Path '${REMOTE_INCOMING}','${REMOTE_SCRIPT_DIR}' | Out-Null\""

echo "[4/6] Upload release package and deployment scripts"
"${SCP[@]}" "$TARBALL" "${TARGET}:${REMOTE_PACKAGE}"
for script in "$PROJECT"/scripts/windows/*.ps1; do
  "${SCP[@]}" "$script" "${TARGET}:${REMOTE_SCRIPT_DIR}/$(basename "$script")"
done

echo "[5/6] Deploy with backup, migration, health check, and automatic rollback"
BACKUP_ARG=""
if [[ -n "$EXISTING_BACKUP_DIR" ]]; then
  BACKUP_ARG=" -ExistingBackupDir '${EXISTING_BACKUP_DIR}'"
fi
"${SSH[@]}" "$TARGET" \
  "powershell -NoProfile -ExecutionPolicy Bypass -Command \"& '${REMOTE_PS_DEPLOY_SCRIPT}' -PackagePath '${REMOTE_PS_PACKAGE}' -Version '${VERSION}' -Commit '${COMMIT}' -McpSourceSha256 '${MCP_SOURCE_SHA256}' -McpBinarySha256 '${MCP_BINARY_SHA256}' -BuildTime '${BUILD_TIME}' -ProjectRoot '${WIN_PS_PATH}'${BACKUP_ARG}; if (-not \$?) { exit 1 }\""

echo "[6/6] Verify deployed version"
DEPLOYED_JSON="$("${SSH[@]}" "$TARGET" \
  "powershell -NoProfile -Command \"Invoke-RestMethod -Uri 'http://127.0.0.1:8000/version' | ConvertTo-Json -Compress\"")"
echo "$DEPLOYED_JSON"
DEPLOYED_VERSION="$(printf '%s' "$DEPLOYED_JSON" | jq -r '.version // empty')"
DEPLOYED_COMMIT="$(printf '%s' "$DEPLOYED_JSON" | jq -r '.commit // empty')"
if [[ "$DEPLOYED_VERSION" != "$VERSION" || "$DEPLOYED_COMMIT" != "$COMMIT" ]]; then
  echo "Deployment verification failed: expected ${VERSION}/${COMMIT}, got ${DEPLOYED_VERSION}/${DEPLOYED_COMMIT}" >&2
  exit 1
fi
"${SSH[@]}" "$TARGET" \
  "powershell -NoProfile -ExecutionPolicy Bypass -Command \"& '${WIN_PS_PATH}\\scripts\\windows\\Assert-ReleaseState.ps1' -ProjectRoot '${WIN_PS_PATH}' | Out-Null; if (-not \$?) { exit 1 }\""
