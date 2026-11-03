# Scheduled advertising account exclusions

## Task and boundaries

- Date: 2026-11-03. Status: local candidate; not deployed.
- User authorized a tested, committed, isolated minimum patch and Windows deployment,
  then configuring the four accounts below. No data deletion, unrelated code release,
  paid image tests, or interruption of active image jobs.
- Base: clean attached worktree `image-async-recovery/web`, branch
  `codex/hotfix-image-async-20261019`, commit
  `a9450172f327e1a27ca4e6860d99bce4e9faa365`; production reports 0.5.0 / a9450172f327.
- Main working directory's existing modifications remain untouched. In particular,
  unreleased report-integrity/history-reconciliation work is NOT part of this patch.
- Common workflow reread: revision 2026-09-30, SHA256
  `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`.
- Risk: R2 scheduling logic, R3 deployment/configuration. No schema, permissions,
  dependencies, image routing, or Phone Cloud changes.

| Advertising account ID | Name |
| --- | --- |
| 10176598 | 上海炎创-云英尔2-1 |
| 10176597 | 上海炎创-云英尔2-2 |
| 11336738 | 东信-新能源早知道-零跑-1 |
| 11692529 | 东信-新能源早知道-2 |

## Behavior and compatibility

`xhs_schedule_settings.config.excluded_account_ids` for `ad_data_refresh` is an
optional list of advertising account IDs. An absent field defaults to no exclusions;
invalid values fail validation rather than silently enabling excluded accounts.
Exclusions apply before token retrieval and before each of the five report queries.
The scheduler summary separately reports configured exclusions, not token failures.

Saving settings through an older admin client preserves an existing list if that
client omits the field; an explicit empty list clears it. Manual report backfills
retain their existing behavior unless the caller explicitly passes an exclusion.
Accounts, owner mappings, historical reports and dashboard queries remain intact.
Aggregate finalization still uses retained raw data, including historical data for
excluded accounts. Creator-center/environment sync is outside this change.

The current run captures its config at start; changes apply to the next run.
Restoring old code alone would ignore this new configuration, so an application
rollback also requires pausing ad refresh until the exclusion-aware version returns.
Do not restore the entire production database to undo this additive JSON field.

## Verification and release checklist

- Python 3.12.13 isolated runtime in `/tmp/web-ad-exclusions-test-20261103`;
  dependencies installed from candidate pyproject without changing lock/source files.
- Test runner disables dotenv and IP connections; SQLite is temporary, no production
  database, upstream reporting, or paid model calls.
- Targeted command: isolated runner with `test_xhs_ad_schedule_exclusions.py`,
  `test_xhs_schedule_service_complete.py`, `test_xhs_service_external_reports.py`:
  **35 passed**, 3 dependency/deprecation warnings, 2.07 seconds.
- First full backend run: 1138 passed, 3 skipped, 32 warnings in 190.74 seconds.
  It was started from `/tmp` without the repository's `.coveragerc`, so the reported
  69.85% coverage failed the gate. This is not accepted as a release pass. A complete
  rerun from `backend/`, explicitly using the unchanged `.coveragerc`, passed:
  **1138 passed, 3 skipped, 32 warnings, 71.43% coverage, 192.52 seconds**.
- Frontend type-check, production build and single-worker coverage suite passed:
  19 files / 189 tests; statements/lines 93.86%, branches 83.66%, functions 75.92%.
- Version-control regression: 16 passed. Alembic head `e61010a0b001`, release contract,
  tracked-secret scan, and `git diff --check` passed; daily version check passed.
- Ruff on changed service files reports two pre-existing findings in `xhs_service.py`
  (unused csv and ambiguous loop variable). Verified the exact findings against HEAD;
  no unrelated lint cleanup included. New test/scheduler code has no findings.
- Source/SQL selection tests are not production verification.
- Self-review: service defaults preserve manual callers; scheduler validates before
  work, filters before external requests, preserves omitted config fields, and never
  updates excluded token/report rows. No independent second reviewer was used.
- Read-only Windows preflight: C approximately 30.1 GB free, D approximately 7.6 GB.
  D fails the existing 20 GB gate; do not bypass it or deploy until resolved.
- Cleanup approved separately by the user: only stopped 0.5.0 rehearsal container and
  its 6.35 GB restore-rehearsal directory, plus unused Docker build cache. Latest dump,
  manifests, production volumes, uploads, current and rollback images must remain.
- Before cutover: verify current version/receipts and immutable rollback artifacts,
  backups/restore evidence, unchanged mounts, no active AI/XHS/Dify/Hermes tasks.
- Only `deploy-to-windows.sh`, with PROJECT pointing to this clean frozen worktree.
- After deploy: verify version/readiness/release state, then transactionally merge
  these four IDs into the ad-refresh configuration, preserving every other field.
  Read back the list and verify excluded IDs cannot enter scheduled token/report
  selection, existing accounts/mappings/history remain, and public service is healthy.
- Observe next scheduled run before claiming real scheduled-run acceptance.
- Read-only schedule inspection: ad refresh enabled at 08:30; account sync and ad
  report publishing disabled. The separate disabled ad-report publishing configuration
  includes the two Yunying'er IDs; it is not changed by this ad-refresh-only patch.
  Review that recipient/account list before anyone re-enables that separate feature.
- Future integration: the main directory's unreleased history reconciliation must
  also receive the exclusion set before that separate feature is released.

## Evidence

Ignored local receipts: `local-reviews/ad-schedule-exclusions-20261103/`.
No credentials or production configuration dumps are tracked.
