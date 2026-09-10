#!/usr/bin/env python3
"""Fail CI when production release safety invariants are weakened."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
deploy = (ROOT / "scripts/windows/Deploy-Release.ps1").read_text(encoding="utf-8")
rollback = (ROOT / "scripts/windows/Rollback-Release.ps1").read_text(encoding="utf-8")
start_production = (ROOT / "scripts/windows/Start-Production.ps1").read_text(
    encoding="utf-8"
)
entrypoint = (ROOT / "deploy-to-windows.sh").read_text(encoding="utf-8")

require(
    compose.count("${APP_IMAGE_TAG:?") == 3,
    "backend, ai-worker and frontend must require APP_IMAGE_TAG",
)
require(
    "${APP_VERSION:?" in compose and "${GIT_COMMIT:?" in compose,
    "Compose must not provide fallback release metadata",
)
require(
    "RELEASE_SOURCE_SHA256" in compose,
    "Compose must pass the release source fingerprint into image builds",
)
require(
    "MCP_SOURCE_SHA256" in compose and "MCP_BINARY_SHA256" in compose,
    "Compose must bind MCP source and binary fingerprints into backend images",
)
require(
    "${Version}-${Commit}-${packageShaShort}" in deploy,
    "production image tags must bind version, commit and package fingerprint",
)
require(
    "Assert-ReleaseState.ps1" in deploy,
    "Deploy-Release.ps1 must run the post-deploy release-state verifier",
)
require(
    "McpSourceSha256" in deploy and "McpBinarySha256" in deploy,
    "Deploy-Release.ps1 must record the exact MCP source and binary",
)
require(
    'Join-Path $releaseRoot "deploy.lock"' in deploy
    and "[System.IO.FileShare]::None" in deploy,
    "Deploy-Release.ps1 must hold an exclusive cross-process deployment lock",
)
require(
    '"predeploy-source-$imageTag.tar.gz"' in deploy
    and '"predeploy-root-$imageTag.env"' in deploy,
    "deployment rollback inputs must be isolated by immutable release identity",
)
require(
    "A newer or equal release" in deploy
    and "refusing stale cutover" in deploy,
    "Deploy-Release.ps1 must reject a stale candidate immediately before cutover",
)
require(
    "com.docker.compose.service=frontend" in start_production
    and "docker start $frontendIds[0]" in start_production
    and "http://127.0.0.1:3000/" in start_production,
    "Start-Production.ps1 must recover and verify the existing frontend without rebuilding it",
)
require(
    "AllowDowngrade" not in deploy,
    "normal deployment must not expose a downgrade switch; use rollback instead",
)
require(
    not re.search(r"docker\s+compose\s+up[^\r\n]*--build", rollback, re.IGNORECASE),
    "rollback must never rebuild a historical release",
)
require(
    "ALLOW_DIRTY_DEPLOY" not in entrypoint,
    "canonical production deployment must not allow a dirty-tree bypass",
)
require(
    "REQUIRE_RELEASE_TAG" not in entrypoint,
    "canonical production deployment must not allow an untagged-release bypass",
)
require(
    '[[ "$VERSION" != "$PACKAGE_VERSION" ]]' in entrypoint,
    "canonical deployment must bind APP_VERSION to frontend/package.json",
)
require(
    "REMOTE_PS_DEPLOY_SCRIPT" in entrypoint and ".release\\\\incoming\\\\scripts" in entrypoint,
    "deployment scripts must be staged outside the live source tree",
)

print("release contract: ok")
