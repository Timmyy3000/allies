# Readiness step timing

## Outcome and scope

Add critical-path evidence to the existing alpha-speed PRs. The product target
is less than five seconds from a user wake/create request to a usable Ally for
new, already-awake and sleeping workspaces. This change measures the path; it
does not establish that the target has been reached.

Extend existing structured events in Cloud, Foundry and the runtime. Separate
provider start calls and observed machine state from authenticated Hermes
health, initial profile reconciliation, runtime readiness and Cloud's committed
product readiness. Preserve existing provisioning and ready-pool timings.

## Boundaries and safety

Use monotonic clocks for in-process durations and label measurements derived
from durable database timestamps as wall-clock intervals. Reuse existing
operation and runtime identities, redact resource identities through the
existing event builders and never include prompts, credentials or URLs.
Concurrent attempts must remain distinguishable. Do not add database writes,
migrations, telemetry services, provider calls or change retry/lease behavior.
Readiness logs must not claim successful persistence before transaction commit.

The user-visible end point is distinct from backend readiness: browser/network
delivery and render time still need client measurement. Do not sum overlapping
phase durations or compare monotonic clocks between processes.

## Delivery and validation

Use the existing Cloud and Foundry PR branches. Runtime and backend changes
are delegated to separate Luna max workers; parent owns Cloud, documentation,
integration and independent review. No HTML is needed for this additive change.

Run focused runtime startup/materialization, backend lifecycle/readiness and
Cloud provisioning/hint/intent tests, plus structured-event privacy and failure
tests. Run lint and broader affected suites after integration. Review simplicity
separately from correctness. Publish changes to the existing PRs without merging
or enabling production features. Revert these additive instrumentation commits
to roll back; no data migration is involved.

Exact local checks use the locked toolchain: `DJANGO_DEBUG=true uv run --locked
pytest -q` in `backend`, `uv run --locked pytest --cov=allies_runtime` in
`runtime`, `uv run --locked ruff check` and `ruff format --check` on changed
Python files, `manage.py check`, `manage.py makemigrations --check --dry-run`,
and `uv run --locked --project backend python scripts/validate.py` from the
repository root. Cloud uses its standard pytest, Django and changed-file Ruff
checks. Verify the shared wide-event fixture remains identical across repositories.

No unresolved product decision blocks this additive work. The remaining risk
is incomplete or misleading evidence: retain critical stages at any sampling
rate, link retry operation identities, keep success commit-aware, and document
the uninstrumented provider/process-start and browser-render gaps.
