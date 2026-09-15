# Immediate file inspection hotfix

## Feature overview

Route: **fast**. Status: revised with applied scanner mitigation (revision 3). HTML is not required:
this bounded operational fix has no visual-review decision. Base: `dev`; delivery
branch: `hot/file-inspection-immediate`.

Uploaded files should start inspection as soon as their durable upload commits.
The current `files.inspect_due_files` task runs every 30 seconds and processes
up to 20 files serially. Its database retries (5 and 30 seconds, three attempts
total) also wait for that sweep. Reported production attempts took about
0.4–0.6 seconds each, but a failed upload took about 100–110 seconds overall.
These timings are investigation evidence supplied by the orchestrator, not a
fresh production measurement by the planning worker.

The observed rejection is `scanner_definitions_stale`. Reported ClamAV startup
logs show FreshClam updating its database before clamd's socket existed, so
NotifyClamd failed. This supports a startup notification race; it does not prove
the current daemon VERSION or establish that immediate dispatch fixes freshness.

Completion has two tracks: this code PR fixes inspection scheduling latency;
the scanner mitigation is operationally applied and verified in staging and
production. The production upload incident stays open until a real upload passes
the fresh-signature scan and completes delivery. App-code merge or deployment
alone cannot close the incident.

## Scope and approach

Use the existing Celery `cloud` queue and database inspection state. Add a task
for one file, publish it after upload commit, and schedule database-owned retries
directly. Keep the existing 30-second bounded sweep as recovery for lost
notifications, expired leases, and broker failure. No new queue, model, migration,
outbox, dependencies, API response, or frontend polling change is required.

Both inbound intake and returned-file publication finish upload by entering
`validating`; cover both boundaries so the shared inspection pipeline behaves
consistently. Preserve all existing size/type/hash checks, isolated parsing,
24-hour scanner freshness policy, malware rejection, private storage, generation
and lease fencing, cancellation/deletion controls, and all-files-ready delivery.
Scanning remains asynchronous; upload requests never execute the parser.

## Contracts and affected surfaces

| Surface | Contract / planned change |
| --- | --- |
| `backend/files/services/inspection.py` | Extract `inspect_file(*, file_id, inspector=inspect_isolated) -> int`: return 0 when nothing can be claimed, 1 when an attempt ran. Reuse `_claim`, `_current`, rejection/retry and promotion without weakening fences. `inspect_due_files` keeps its public signature and bounded query, delegates each ID to this operation, and sums results. |
| `backend/files/tasks.py` | Add internal Celery task `files.inspect_file` accepting one canonical UUID string, returning 0 or 1. Invalid IDs fail before database/storage work. Set no Celery automatic retries: persisted attempts/due time remain authoritative. Keep existing batch/cleanup entrypoints compatible. |
| `backend/files/services/inspection.py` or a small existing-style dispatch helper | `enqueue_file_inspection(file_id, *, countdown=0) -> None` uses a local task import to avoid the intake/inspection import cycle, serializes UUID, targets `cloud`, and catches publish failures with privacy-safe evidence. Use a short-lived producer connection scoped to this helper: `connection_for_write(connect_timeout=1, transport_options={"socket_connect_timeout": 1, "socket_timeout": 1, "retry_on_timeout": False})`; publish through that connection with `retry=False`, and close it afterward. Preserve inherited transport options. Avoid the shared producer-pool wait and do not change consumer sockets. It must not turn a committed upload into an HTTP error. |
| `backend/files/services/intake.py` | In the final `receive_file` transaction, register a post-commit callback after persisting `validating`; capture the ID by value. No enqueue for rolled-back, incomplete, conflicted, or cancelled uploads. |
| `backend/files/services/publication.py` | Register the same callback after a returned file durably enters `validating`. Preserve publication reconciliation and accounting. |
| `_retry` in inspection service | Persist attempts/due time and release the lease first. For attempts 1 and 2 register post-commit notification with ETA/countdown aligned to the persisted 5/30-second due time. No notification after terminal rejection or stale claim. An early or duplicate delivery cannot bypass the due-time condition. |
| `backend/config/settings.py` | Retain the 30-second sweep, its `cloud` route, and bounded page size; document its recovery purpose only if helpful. |
| `docs/operations/file-inspection.md` | Document immediate dispatch, durable fallback, privacy-safe timing evidence, and the scanner startup/freshness release gate below. |

Queue example: task `files.inspect_file`, args
`["00000000-0000-4000-8000-000000000001"]`, queue `cloud`, countdown `0` initially.
The ID is an internal routing hint, never file bytes, names, storage keys, or
credentials. A delayed old message may at most prompt inspection of the current
eligible row; the worker must obtain a fresh generation-specific lease before
I/O and use its existing fences for every result write. Duplicate messages,
direct tasks racing the sweep, future-due rows, live leases, terminal rows,
missing rows and deleting Allies must safely no-op.

## Phases

1. **Implement dispatch and retry.** Extract the existing per-row body with
   minimal behavioral changes; add the task/helper and both upload hooks. Keep
   notification failure recoverable from committed database state. Add focused
   tests in `backend/files/tests/test_intake.py`, publication tests, and a small
   task/service test module only if existing files become unwieldy.
2. **Validate safety and timing.** Run the checks below. Independently review
   simplicity and correctness. Inspect the final diff for unrelated changes and
   keep one coherent PR into `dev`, with required AI coauthor attribution.
3. **Retain scanner mitigation and verify the upload.** Operational work has
   applied `CLAMD_CONF_SelfCheck=10` in staging and production using the official
   image's supported `CLAMD_CONF_*` entrypoint configuration. Official clamd
   configuration documents a 600-second default; the 10-second check interval
   makes the daemon check for updated signatures promptly after a missed startup
   notification. This mitigates the race without changing startup ordering or
   weakening freshness checks. Both environments retain `FRESHCLAM_CHECKS=12`,
   their persistent signature volumes, default entrypoint, and no start-command
   override. Both run `clamav/clamav:1.5.4_base-debian13-slim` at digest
   `sha256:0481636f876a3d338ab2a9871888f8a75968f428a423e872ec98a73c6687e1ce`.
   Staging deployment `f87c6dbc-1b55-45fa-a279-3a11dcb5578a` and production
   deployment `09a195ab-6063-43e8-988a-0f4a88b9d201` reached SUCCESS; each logs
   `Self checking every 10 seconds` and `SelfCheck: Database status OK`.
   These orchestrator-verified logs establish that the mitigation is active;
   they do not replace a real accepted scan/upload. Record a real upload and
   fresh-signature scan result before incident closure. Preserve the setting
   across future deployments and verify the interval and database status again.
4. **Promote and observe.** Use existing dev → staging → production workflows.
   Deploy all workers recognizing the new task before any producer emits it.
   If Railway cannot sequence worker then web, use two promotions: first the
   extracted single-file service/task plus compatible sweep, with upload and
   retry emission absent; verify every old worker has stopped and all current
   workers register `files.inspect_file`. Then promote the upload/retry hooks.
   Keep these as coherent commits so the existing promotion workflow can select
   the consumer-only revision. This avoids relying on unknown-task loss; the
   normal 30-second recovery sweep remains active throughout both phases.
   Verify matching revisions and task registration, scanner freshness, then
   perform a fresh small-PDF upload and failed-file retry through the real UI.
   Record upload commit, task start, completion and displayed state timings;
   correlate with safe IDs only. Update the canonical Nabu attachment note with
   verified behavior and operational lesson, revision-aware. Monitor PR checks
   and required reviews; do not conflate PR readiness with deployed completion.

## Acceptance and validation

1. With beat paused in a test environment and a healthy idle worker/scanner, one
   uploaded file reaches `ready` through the new task; other uploads need not
   finish first. Target commit-to-task-start under 2 seconds for repeated small
   PDF trials; report observed scan/UI duration separately. This is a validation
   target, not a guarantee under queue saturation or a slow scanner.
2. Post-commit tests prove no task publication before commit or after rollback;
   the task can see the committed object/state. Broker failure leaves the upload
   successful and validating; the next eligible recovery sweep completes it.
   Assert actual Redis connection parameters and disabled publish retry, then
   exercise a refused connection, a controlled connection timeout, and a local
   TCP peer that accepts but never responds. Measure helper return within 3
   seconds in each controlled case, including connection cleanup, and prove
   sweep recovery afterward. These are per-operation socket budgets, not a hard
   deadline over arbitrary DNS/OS stalls; record that limitation. No existing
   Celery connection or transport timeout is configured in settings, so do not
   claim inherited defaults bound this path. If the locked Redis/Kombu version
   retries despite these options, explicitly disable that retry in the scoped
   connection and repeat the fault tests before accepting the implementation.
3. A retryable failure schedules attempts at persisted 5/30-second delays with
   beat paused, never before due; attempt three rejects and reconciles once.
   Lost retry publication is recovered by the sweep. Preserve original safe
   error classification and attempt ceiling.
4. Direct and sweep tasks racing on PostgreSQL produce one active lease and one
   accepted state transition. Cover duplicate delivery, an active/expired lease,
   future due time, missing/terminal rows, cancellation/deletion and replacement
   generation. Existing promotion fencing and publication tests remain green.
5. Malware, stale definitions, parser/storage timeout and promotion failures
   remain fail-closed. A multi-file message is delivered once only after every
   file is ready; failed files and successful uploads retain current retry rules.
6. Scanner mitigation configuration and self-check logs are verified in both
   environments. Remaining release proof is a benign live upload accepted by
   the actual freshness-enforcing scanner, with successful delivery; capture
   daemon VERSION when accessible. Record failed update/reload behavior: no file
   is accepted until signatures are fresh. Production retest of the reported PDF
   requires user-provided bytes or their retry; a synthetic PDF proves the
   pipeline only. Keep the incident open until a real upload passes.

Inspected validation sources: `README.md`, `Makefile`,
`.github/workflows/ci.yml`, and `backend/pyproject.toml`.

- From `backend/`: `uv sync --locked`, `uv lock --check`.
- From repository root: `make check`, `make lint`, `make test APP=files/tests`.
- From `backend/`: `uv run ruff format --check .`; use repository formatting
  conventions for changed code and inspect formatting diffs.
- Against a disposable PostgreSQL database: `uv run pytest -m postgresql` and
  `uv run pytest files/tests`; SQLite cannot prove row-lock concurrency.
- Required CI also runs full pytest, migrations/apply-check, and AUTH-001
  coverage. Require its green results at the final PR revision. Record local
  platform limitations honestly; isolated parser proof requires POSIX.

## Risks, rollout and rollback

- The shared worker defaults to concurrency 1. Immediate notification removes
  scheduler delay but cannot bypass a busy worker or make scanning instantaneous.
  Measure backlog before considering additional worker capacity; no new capacity
  or queue topology is part of this hotfix.
- Publish occurs after commit without an outbox. Process death or broker failure
  can lose the notification; the retained due-row sweep is the explicit recovery
  contract. Existing 240-second leases bound worker-crash recovery.
- Faster retries exhaust in roughly 35 seconds plus actual work. A persistent
  stale scanner still rejects; verify scanner health before calling this fixed.
- Mixed worker versions can discard unknown tasks. Upgrade consumers before
  producers. For rollback, stop new producers first and let new workers drain
  queued/countdown tasks before reverting them; retain the sweep and data.
  Reverting dispatch code restores prior sweep behavior without a migration.
- Operational rollback removes `CLAMD_CONF_SelfCheck` or restores its default
  value `600`, then redeploys and verifies the interval/database status. This
  restores the longer missed-notification recovery delay; it does not revert
  signature data. Retain `FRESHCLAM_CHECKS=12` and the volumes. Do not bypass
  freshness, replay rejected production rows, or disable fail-closed checks.

## Evidence and open decisions

Canonical baseline inspected: Nabu `projects/allies/index.md` and
`projects/allies/engineering/specs/cld-010-user-message-file-attachments.md`
(approved product scope plus later accepted corrections). Local inspection:
`AGENTS.md`, `ENGINEERING_STYLE.md`, intake/inspection/tasks/publication,
inspection and intake tests, scheduler, operation docs, README/Makefile/CI/test
configuration. No product-contract mismatch requires a scope change.

Revision 2 also inspects installed Celery `connection_for_write` and Redis
transport support for `socket_connect_timeout`, `socket_timeout`, and
`retry_on_timeout`; configured settings currently contain none of these limits.
The full scanner digest, supported entrypoint/configuration and deployment logs
in revision 3 are orchestrator-verified inputs, not independent deployment
inspection by this worker.

Adversarial dispositions: P1 scanner completion split accepted; P2 broker
latency accepted with scoped producer timeouts and real fault tests; P2 mixed
worker rollout accepted with a concrete two-promotion fallback.

No product decision or scanner-remediation choice remains unresolved. The
supported SelfCheck mitigation is applied and log-verified in both environments.
The remaining incident gate is real upload success; the shorter interval is not
a guarantee of scan duration, reload duration, or successful signature download.
