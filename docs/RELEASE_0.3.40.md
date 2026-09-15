# v0.3.40 FRP tunnel stability hotfix

Updated: 2026-09-15

## Root cause

- The Windows web application and Docker containers remained healthy while the FRP process entered a stale state: its control process stayed alive, but public work connections stopped forwarding requests.
- The client requested 30 pre-created work connections while the server accepted at most 20. This pool is not the public-user concurrency limit, and a large pool adds little value while FRP TCP multiplexing is enabled.
- The previous watchdog ran once per minute and required two failed runs, leaving a stale public entry visible for roughly two minutes.

## Fix

- Use five pre-created work connections, explicit TCP multiplexing, a 10-second multiplexing keepalive, and a 15-second server dial keepalive.
- Run the public-entry watchdog continuously every 10 seconds. Two consecutive public failures while the local page remains healthy restart only `frpc`.
- Keep the FRP task and watchdog under Task Scheduler restart supervision and rotate the watchdog log at 5 MB.
- Validate the candidate FRP config before applying it and automatically restore the previous config if the public entry does not recover.
- Preserve and explicitly validate the complete `[[proxies]]` section when generating the candidate config; a failed candidate can no longer pass validation with an empty proxy list.

## Release boundary

- Do not restart Docker, PostgreSQL, Redis, MinIO, the core backend, AI workers, or Hermes workers.
- Back up `C:\ProgramData\frp\frpc.toml` before the one-time FRP client restart.
- Verify both the LAN page and public page repeatedly after installation.
