# Image Async Transport Hotfix

## Scope And Authority

- Task: `20261019-image-async-recovery`; status: local candidate, not deployed.
- User approved local implementation, tests, frozen minimal commit and Windows deployment after validation; at most two real image tests, no publication. Drain in-flight tasks; do not restart Docker or the proxy, mix unrelated changes, or resubmit the eight original unknown image results.
- Separate cleanup approval permits unused Docker build cache and confirmed obsolete release temporary packages only. Preserve current/rollback images, latest backup, database, galleries, task records and other projects. Stop if space remains insufficient.
- Re-read AGENTS and shared workflow, revision 2026-09-30, SHA256 `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`.
- Risk R3 for production; R2 for async lifecycle/reconciliation code. No schema migration or API/permission changes. Existing shadow/reconciliation flags must not be enabled implicitly.

## Baseline And Evidence

- Clean emergency worktree: `/Users/yyx/.codex/worktrees/image-async-recovery/web`, branch `codex/hotfix-image-async-20261019`, based on production `e6a18580c7782db6bea4140b87544e4753573654` / 0.4.1.
- Original dirty workspace `/Users/yyx/ztqc/web` remains untouched. Its copy-model error handling and other pending work are excluded.
- Original runs 115/116: fifteen copy results passed; seven images succeeded and eight image outcomes were unknown. Tasks 39701, 39705, 39711, 39713, 39715 timed out on provider 12 at approximately 290 seconds. Tasks 39718, 39724, 39726 returned HTTP 502 on provider 5.
- Relay logs correlate those three 502 request IDs with native upstream EOF/connection-reset failures. Async transport does not repair that independent network failure; it avoids keeping a browser-to-provider request open and records accepted task IDs for GET-only recovery.
- GET-only provider-5 capability probe returned `IMAGE_TASK_NOT_FOUND` for a nonexistent task, rather than a disabled/absent async route. No real image POST has been made by this hotfix task yet.
- Internal relay contract: [Sub2API async image tasks](https://github.com/Wei-Shaw/sub2api/blob/main/docs/ASYNC_IMAGE_TASKS.md). POST generation/edit `/async`, persist the receipt, GET `/images/tasks/{id}`. Ignore supplier poll URLs/redirects. No guaranteed POST idempotency is assumed.

## Candidate Behavior

- Only `openai_images` providers with existing JSON config `api_mode=sub2api_async` change protocol. All other providers retain their prior protocol and routing.
- Persist a pending dispatch before each POST; clear it only on confirmed non-dispatch/rejection or durable upstream acceptance. A missing receipt is not permission to regenerate. Cancellation prevents the next image submission; accepted work remains queryable.
- Poll by stored ID using the same provider origin/key. GET interruptions retry GET only; never retry an ambiguous POST or silently use the sync endpoint.
- Persist expected count per accepted upstream task; preserve partial images, aggregate delayed results across polling rounds, and validate final requested count.
- A later unreceipted submission cannot be resolved by an earlier successful image. Known accepted images can still be recovered; uncertainty remains for manual reconciliation.
- Durable provider diagnostic tasks use the same acceptance recording. Direct async diagnostics without durable recording are refused.
- If shadow/reconciliation flags are disabled, normal in-process polling still works, but automatic recovery after worker loss is not claimed. Activation of those global flags requires separate verification/approval.

## Verification And Deployment Gates

- Python 3.12.13 isolated environment `/tmp/web-image-async-runtime-20261019`; exact project dependency pins, no dependency-file upgrades. Tests clear credentials/dotenv/proxies, block external sockets and business DB/Redis ports, use temporary SQLite and mocked providers.
- Initial adapter tests: 23 passed. Expanded adapter tests: 27 passed. Initial targeted regression: 167 passed.
- First full backend: 1073 passed, 3 skipped, 31 warnings, branch-inclusive total coverage 71.25%, 359.01 seconds. Subsequent cancellation/recovery fixes require a final full rerun before freezing.
- Frontend type check, coverage suite and production build passed with unchanged frontend business source. Specified-range statement/line coverage 93.86%, branch 83.66%, function 75.92%. Version metadata is advanced consistently to 0.4.2; no dependency changes.
- Ruff changed Python files, Alembic single-head (`e61010a0b001`), release contract and tracked secret scan passed. No new migration is introduced. Local checks do not imply production acceptance or remote CI/branch protection.
- Windows preflight: core receipt/runtime still 0.4.1/e6a18580c778. Initial free space C approximately 4.9 GiB, D approximately 8.1 GiB; database approximately 6.8 GiB. Required C database-size + 8 GiB and D 20 GiB are not satisfied. Do not invoke deployment or paid canaries until gates pass.
- Authorized cleanup initially removed approximately 3.3 GB of old unused builder cache; Windows host free space did not increase. Docker virtual-disk free space is not the same as host free space. No compaction/restart, images, volumes, business files or backups were removed.
- Final test/review/freeze and latest disk evidence will be appended below. Production package/image/backup/restore/release receipt and real-image checks remain unverified until actually executed.

### Final Local Verification

- Final full backend rerun: **1074 passed, 3 skipped, 31 warnings; 71.26% coverage; 244.78 seconds**. The preceding full run encountered a scheduler-leader SQLite lock, followed by twelve fixture errors (1062 passed, one failed). Scheduler-only rerun: fourteen passed. The clean final full rerun passed without excluding tests or changing scheduler code, test timeouts or thresholds. This incident remains recorded rather than hidden.
- Latest focused regression after cancellation fixes: eighty-nine passed. Independent read-only review re-ran twenty-seven adapter tests and double-cancellation probes; final conclusion: no remaining code blockers. This is not a PostgreSQL concurrency or production acceptance result.
- Frontend: nineteen files / 189 tests passed, statement/line 93.86%, branch 83.66%, function 75.92%; type check and production build re-ran successfully after the 0.4.2 metadata bump.
- Version-control regression: sixteen passed. An attempted `test_release*.py` discovery matched zero files and exited nonzero; it is not counted as a passing check. Existing release-contract and single-head checks passed separately.
- Windows cleanup: `docker builder prune --force --filter until=168h` removed 3.288 GB; a second `--all` pass removed 6.136 GB. Only unused build cache was removed; image/volume/container prune was not run. Host free space remains **C 4.85 GiB / D 7.89 GiB**. No old release package was deleted because none was needed to justify an unsafe partial-space workaround.
- Current Windows `/health/ready` returns ready with database, Redis and local storage OK, still version 0.4.1 / e6a18580c778. Actual AI worker flags are shadow=false, reconciliation=false; no automatic post-crash recovery is claimed and neither flag was changed.
- **Deployment blocked, not attempted:** minimum C headroom approximately 14.8 GiB (current database plus 8 GiB), D 20 GiB. The user explicitly required stopping if approved cleanup is insufficient. Disk compaction, Docker/proxy restart, deleting immutable release artifacts/backups, or broader cleanup has not been authorized or performed.
- Real image tests consumed: zero of the maximum two. No provider configuration or old failed/unknown task was changed. Production backup restore rehearsal, image build, canary generation and release receipt validation remain pending.

## Release And Rollback

When all gates pass: use clean tagged HEAD via `deploy-to-windows.sh`; prebuild before closing ingress; verify task drain, current receipt, production mounts, full recoverable backup and restore rehearsal, unchanged migration head, candidate health and MCP identity. Preserve Hermes component receipt and runtime configuration.

After code deployment, back up provider 5 JSON config and opt in only that provider; do not change provider keys, weights, concurrency, other models or proxy nodes. Perform at most two scoped real image tests. Verify persisted upstream IDs, GET polling, final image count, postprocessing/storage/access and ordinary app smoke tests. Stop on regression or unknown image results; do not compensate with duplicate generation.

Rollback uses the actual immutable 0.4.1 image/package and prior provider config; preserve all new business writes. No database restore is needed for this schema-free patch. Do not alter the trusted release receipt manually or rebuild an old mutable tag.
