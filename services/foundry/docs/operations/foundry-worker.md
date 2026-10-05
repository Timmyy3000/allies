# Persistent Foundry worker

Run one background process alongside the API and database:

```sh
uv run --no-sync python manage.py run_foundry_worker
```

It runs four independent loops: event delivery, profile-readiness hints,
runtime power/publication maintenance, and ready-pool maintenance. Each pass
uses the existing durable service functions and bounded batches. Slow provider
work in the pool or power loop does not block the delivery loops. A failed pass
is retried by the next pass; existing durable retry budgets still apply.

Use the same database, service credentials, runtime images and workspace/pool
settings as the API. Keep one worker replica and no public endpoint. Disable
traffic-based service sleeping for this background process so timers and queued
work continue without inbound HTTP requests.

SIGTERM or SIGINT requests shutdown. All loops share a maximum 30-second grace
period. A dead loop or exceeded shutdown deadline exits with failure so the
deployment platform can restart the process. In-flight provider operations may
have an uncertain outcome; the existing durable reconciliation paths recover
them after restart.

For a bounded operator check, `--max-runs 1` runs one pass of each loop. This
performs real work; it is not a dry run. `--shutdown-grace` may shorten the
shared grace period but cannot extend it beyond 30 seconds.

## Replace existing publishers

Deploy compatible code first. Record the old worker commands and resource
usage, then stop the event publisher, readiness publisher and pool maintainer
before starting the combined worker. Verify delivery, runtime wake/idle work,
pool replenishment and restart recovery before retiring the old services.
Compare CPU and memory over equivalent workloads and observation windows.

To roll back, stop the combined worker, restore the previous commands and
matching environment settings, then verify all three loops resume. Preserve
database state and provider resources throughout the handoff.
