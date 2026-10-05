# Profile cleanup expiry

Foundry keeps cleanup-pending runtime profiles fenced until their bounded grace
window expires. Expiry is server-owned and idempotent: rerunning the command
does not create another transition or receipt for an already expired profile.

Run a single expiry pass from the repository's backend directory:

```powershell
cd backend
uv run --locked python manage.py expire_profile_cleanups
```

For deployments that want the process to poll without adding a scheduler
dependency, run the bounded watch mode under the deployment process's normal
restart policy:

```powershell
cd backend
uv run --locked python manage.py expire_profile_cleanups --watch --interval 60 --max-runs 60
```

This performs at most 60 passes, waiting 60 seconds between passes, and exits
after the final pass. `--watch` requires `--max-runs`; `--interval` accepts
1-3600 seconds and `--max-runs` accepts 1-1440 passes. A cron or platform
scheduled job can use the one-shot command instead.
