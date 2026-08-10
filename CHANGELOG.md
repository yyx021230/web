# Changelog

All notable changes are recorded here. Versions follow semantic versioning.

## [0.3.0] - Unreleased

### Added

- Additive durable job tables for jobs, batch items, worker attempts, and audit events.
- A validated job state machine with idempotent creation, monotonic progress, cancellation requests, retry scheduling, and dead-letter handling.
- PostgreSQL/SQLite atomic idempotency through native conflict handling without committing the caller transaction.
- Atomic worker claiming, lease ownership, heartbeats, expired-lease recovery, bounded retries, and cancellation-priority recovery.
- A disabled-by-default homepage-sync shadow adapter that mirrors legacy batch/account outcomes and parity without executing duplicate work.
- An admin-only homepage shadow parity report that independently compares legacy and durable records before execution migration is allowed.
- A disabled-by-default AI image shadow lifecycle that records generation phases and isolates uncertain upstream outcomes for reconciliation without taking execution ownership.

### Not Yet Connected

- Existing AI, Dify, Xiaohongshu publishing, report, and homepage-sync execution still use their current paths; AI generation and homepage sync are connected only for optional shadow observation.
- Durable worker integration and the unified task-center API will be added in subsequent v0.3 steps.

### Known Migration Risk

- The new `4d5e6f7a8b9c -> 5e6f7a8b9c0d` migration is upgrade/downgrade verified. A pre-existing empty-SQLite migration-chain failure remains at revision `6ac6769ce0b2` and must be fixed before treating empty-database recovery as validated.

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
