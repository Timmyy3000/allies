# Test Ally creation timing locally

Use local Cloud, Foundry and web for fast regression checks before deployment.
Keep the three creation cases separate: first workspace, another Ally in an
awake workspace, and another Ally in a sleeping workspace.

## Fast checks

Run Cloud provisioning and concurrency tests against PostgreSQL to exercise
row locks; the SQLite run skips the PostgreSQL concurrency cases. Run the
Foundry runtime tests directly to exercise the actual worker's reconciliation
and claim cadence with a controlled clock.

```powershell
# Cloud backend directory
uv run --locked pytest allies/tests/test_provisioning.py allies/tests/test_concurrency.py

# Foundry runtime directory
uv run --locked pytest tests/test_foundry.py tests/test_profile_reconciliation.py
```

## Local browser smoke test

From the Foundry repository, use the existing isolated Docker proof. Supply
the Cloud and Interface checkouts containing the versions being tested.

```powershell
python scripts/prove_fnd009.py `
  --cloud-root ../allies-cloud `
  --interface-root ../allies-interface
```

The runner starts local databases, Cloud API/Celery, Foundry, a Fly simulator,
and web, then runs the browser wake/stream/sleep/wake test. It uses existing
local-only fake authentication, so Google signup is not needed. It creates
unique Docker project names and cleans up its own containers and volumes.
Use `--no-cleanup` to retain the backend stack for investigation; the web
process still stops when the runner finishes.

The simulator uses a fixed polling interval and preseeded profiles. This is
an orchestration regression test, **not a measurement of the production
runtime loop or new-machine provisioning**. Do not infer real Fly startup
or model latency from its elapsed time.

## Real runtime check

For real Fly-backed testing with local services, follow Foundry's
`docs/operations/local-fly-docker.md` and Cloud's
`docs/engineering/local-staging-docker.md`. A runtime on Fly needs a reachable
Foundry endpoint; localhost alone is insufficient. Use a dedicated test
workspace and the existing authentication setup. Google testing requires an
authorized localhost callback on the OAuth client, as documented there.

Capture each phase from persisted timestamps and privacy-safe runtime events:
creation, profile materialization, Cloud confirmation, execution persistence,
claim, first text, completion, and browser display. Report browser observation
time separately from the actual render time. Record build revisions and whether
the machine was awake or asleep. A local functional pass does not close the
alpha latency report; repeat the three cases on the deployed build before
claiming an improvement in real startup latency.
