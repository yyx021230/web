# 0.3.43 Windows release

## Scope

- Core web: AI image task routing, result-count integrity, progress and prompt tools; prompt gallery feed and picker; manual creator-center import support.
- Hermes: editorial variation, copy length and voice controls, with accompanying worker tests.
- No application schema migration in this release. Keep the production database, uploads, `.env` files, and image-provider configuration intact.

## Gates

1. Commit the release source and tag the same commit `v0.3.43`. Package only tracked source; exclude local exports and scratch files.
2. Pass backend tests with at least 70% runtime coverage, frontend coverage/type-check/build, Hermes tests, secret scan, release-contract check, and single Alembic head check.
3. Confirm Windows C and D free-space gates, verify the most recent database backup, and drain AI, XHS, Dify, and Hermes queues. Do not cancel active user jobs to speed up the release.
4. Use `deploy-to-windows.sh` for the core release, then `deploy-hermes-worker-to-windows.sh` for Hermes when its queue is empty and schedule is disabled. Never update source with an ad-hoc tar extraction or `docker compose up --build`.

## Acceptance

- Verify the backend `/version` matches `0.3.43` and the tagged commit; run `Assert-ReleaseState.ps1` and inspect all production container health states.
- Check homepage/prompt-gallery images and detail view, gallery assets, login, AI task submission/status/history, prompt tools, manual creator-center import entry, and Hermes workflow entry.
- Confirm existing user tasks and stored images remain accessible. If health or data checks fail, use the release rollback script and the verified pre-cutover backup instead of manually changing database contents.
- Keep only the newest complete backup on Windows after the new release is verified; move older backups off-host and check their SHA-256 hashes before removal.
