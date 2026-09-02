# Changelog

All notable changes are recorded here. Versions follow semantic versioning.

## [0.3.18] - 2026-09-02

### Fixed

- Scheduled Creator Center synchronization now excludes browser runner environments with the same rule used by the execution service.
- Incomplete Xiaohongshu account configurations are skipped during scheduled preflight instead of aborting the entire account batch.
- Accounts that fail the first Creator Center pass are retried once without rerunning successful accounts.

## [0.3.16] - 2026-08-24

### Fixed

- Creator Center engagement sync now defers phone-busy accounts to a bounded tail queue instead of failing them immediately.
- Phone verification submission now waits up to three minutes for the existing Xiaohongshu page to become interactive.

### Changed

- Windows releases now build and validate candidate images before briefly closing the frontend for the final switch.

## [0.3.15] - 2026-08-21

### Fixed

- Creator Center imports now reserve exact post-ID and stable-fingerprint matches before title fallback, preventing a newly reused title from taking an older post and triggering the per-account creator-key uniqueness constraint.
- Same-title Creator Center rows with known, materially different publish times are now treated as different posts instead of being linked by title alone.
- Windows releases can now preserve the rollback image when the frontend was already stopped for a maintenance window.

### Changed

- Xiaohongshu administration now exposes enterprise/employee/personal account types in the environment directory, adds account-type filtering, and labels the SMS-first versus QR-first login strategy.

## [0.3.14] - 2026-08-21

### Changed

- Homepage-note synchronization now lets selected YunDeng runners execute concurrently without an obsolete in-process lock serializing them.
- Homepage enrichment sizes its scroll from all Creator Center notes, including notes whose feed IDs still need to be resolved.
- SMS-timeout fallback now reopens the Xiaohongshu homepage and captures a fresh QR code before dispatching the phone scan task.
- Windows releases now close the frontend before the first queue gate so new image tasks cannot race candidate-image builds, and an early gate failure reopens only the frontend without restarting a worker that is still draining accepted work.

## [0.3.13] - 2026-08-21

### Changed

- Xiaohongshu enterprise-account login now sends the primary SMS only once and switches to QR login when that SMS is not received.
- The QR fallback arms its secondary SMS receiver before dispatching the phone task, preserving automatic post-scan verification.

## [0.3.0] - Unreleased

### Added

- Additive durable job tables for jobs, batch items, worker attempts, and audit events.
- A validated job state machine with idempotent creation, monotonic progress, cancellation requests, retry scheduling, and dead-letter handling.
- PostgreSQL/SQLite atomic idempotency through native conflict handling without committing the caller transaction.
- Atomic worker claiming, lease ownership, heartbeats, expired-lease recovery, bounded retries, and cancellation-priority recovery.
- A disabled-by-default homepage-sync shadow adapter that mirrors legacy batch/account outcomes and parity without executing duplicate work.
- An admin-only homepage shadow parity report that independently compares legacy and durable records before execution migration is allowed.
- A disabled-by-default AI image shadow lifecycle that records generation phases and isolates uncertain upstream outcomes for reconciliation without taking execution ownership.
- Cancellation-safe AI upstream task-ID capture, restart duplicate-submission protection, automatic status reconciliation, and audited manual resolution for uncertain image outcomes.
- Admin-only AI reconciliation list, retry, and manual-resolution endpoints that exclude prompts and Provider credentials.
- Admin-only unified durable-job list and detail endpoints with bounded evidence, fixed-query loading, and server-side secret redaction.
- A read-only reliable-task tab in the existing admin task center with workload summaries, filters, progress, item outcomes, attempts, and an event timeline.
- A disabled-by-default Xiaohongshu report-refresh shadow adapter for manual refreshes and the configured scheduled refresh, with persistent per-report evidence and no duplicate upstream execution.
- An admin-only report-refresh parity endpoint that independently detects missing, duplicate, orphaned, or altered shadow jobs before any execution cutover.
- A disabled-by-default Dify task shadow that mirrors user/admin workflow lifecycle evidence without copying input or output content and without issuing a second Dify request.
- An admin-only Dify parity report with fixed-query missing/duplicate/orphan detection, deletion audit snapshots, and cancellation-versus-late-success drift reporting.
- Disabled-by-default engagement/detail sync shadows with per-account terminal evidence, low-write detail mirroring, independent parity reporting, and persistent queued-cancellation closure.
- Database-backed scheduler Leader election with atomic renewal, bounded failover, fail-closed loop cancellation, child-loop supervision, and an admin health endpoint.

### Not Yet Connected

- Existing AI, Dify, Xiaohongshu publishing, report-refresh, and homepage-sync execution still use their current paths; available shadow adapters observe selected flows but do not replace their legacy execution owners.
- Scheduler leadership prevents duplicate polling across healthy API replicas, but scheduled triggers do not create executable durable jobs until each business flow passes its worker-cutover gate.
- Durable worker integration and operator controls such as cancellation or failed-item reruns will be added in subsequent v0.3 steps.

### Fixed

- Repaired the historical empty-database migration chain by restoring the required Dify and material schema, removing duplicate baseline indexes, and making the corresponding SQLite downgrade reversible.
- Added an empty-database upgrade/downgrade/re-upgrade regression covering the complete Alembic graph and the v0.3 task tables.

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
