"""Application build metadata exposed by health and version endpoints."""

from __future__ import annotations

from app.config import settings


def get_build_info() -> dict[str, str]:
    return {
        "version": settings.app_version,
        "commit": settings.git_commit,
        "buildTime": settings.build_time,
        "environment": settings.deployment_environment,
    }
