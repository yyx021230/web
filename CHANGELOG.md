# Changelog

All notable changes are recorded here. Versions follow semantic versioning.

## [0.2.0] - Unreleased

### Added

- Development, test, and production environment guards with isolated test databases.
- Public `/version` build metadata and dependency-aware `/health/ready` checks.
- Request IDs and request duration metadata for API tracing.
- GitHub Actions checks for backend tests, frontend build, Alembic graph, secrets, Compose, and Docker images.
- Versioned Windows release pipeline with pre-deploy backup, migration, health validation, and automatic rollback.
- PostgreSQL and upload backup/restore scripts, daily backup scheduling, and restore confirmation guards.
- Windows health monitoring for services, disks, database connections, Redis queues, and backup age.

### Changed

- Application, Python, Node, PostgreSQL, Redis, and MinIO release versions are pinned.
- Docker services now have log rotation, resource limits, and health checks.
- Frontend and admin navigation display the running application version and Git commit.
- Legacy internal deployment now reuses the canonical production Compose definition.
- Test fixtures use process-isolated SQLite databases and current authentication behavior.

### Fixed

- Restored cloud browser fingerprint/start configuration before browser launch.
- Fixed immediate Xiaohongshu publish scheduling when `ai_origin_type` is supplied.
- Updated stale tests to match current workflow and synchronization behavior.

### Not Included

- Domain, HTTPS, and public traffic cutover remain deferred.
- Unified persistent job center and multi-tenant isolation are planned for later versions.
