# Execution Manifest

## Shared Context

- Work brief: `docs/plans/cld-003-kickoff.md`
- Accepted plan: `docs/plans/cld-003-create-and-manage-real-ally.md`
- Review dispositions: the work brief's adversarial, simplicity, and product-owner simplification sections
- Repository instructions: `AGENTS.md`, `ENGINEERING_STYLE.md`
- Worktree: `E:\Users\Oluwatimilehin\Documents\Programming\helpers\allies-cloud\.forest\worktrees\ft\cld-003`
- Implementation mode: delegated `always`, using native `luna_execution_worker`
- Naming rule: delivery-ticket identifiers belong only in planning prose, never code symbols, runtime schemas, routes, migrations, events, or contract filenames

## Task CLOUD-MODELS

### Objective

Implement the minimal durable `allies` domain foundation: models, constraints, migration, state derivation, and focused model tests.

### Dependencies

- Accepted plan and owner simplification decisions.
- Existing `AuthFlow`, Workspace, identifier, and Django model conventions.

### Owned Files Or Systems

- `backend/allies/models.py`
- `backend/allies/apps.py`
- `backend/allies/__init__.py`
- `backend/allies/migrations/`
- `backend/allies/tests/test_models.py`
- `backend/allies/tests/__init__.py`
- The smallest necessary `backend/config/settings.py` app-registration edit

### Required Context

- Activate the `ponytail` skill at `full` intensity before editing and confirm it in the result; accepted requirements and safeguards take precedence.
- Reuse existing patterns. Do not add an outbox, provider reference, Ally lifecycle field, gateway abstraction, retry endpoint, or ticket-derived identifier.
- Do not modify API, service, task, gateway, contract, or Foundry files.

### Acceptance Criteria

- `Ally`, `AllyBinding`, `OnboardingAttempt`, and `ProvisioningOperation` match the accepted plan's minimal data shapes.
- Database constraints enforce immutable one-to-one binding identity and unique `(workspace, user, api_idempotency_key_digest)` operation identity.
- Attempt data stores only digests, supports expiry/single consumption, and may associate one user and Ally.
- Public provisioning state derives from binding/operation; it is not persisted on `Ally`.
- Operation contains the minimal lease, attempt count, next-attempt, expiry, and safe evidence fields needed by existing Celery/beat.
- Start meaningful logic with failing tests where practical; migration is additive and domain-named.

### Validation

- Run the smallest focused model test command supported by the repository.
- Run Django migration consistency/checks relevant to the new app when practical.

### Required Result

- Files changed
- Tests and results
- Assumptions
- Blockers
- Integration notes

## Task CLOUD-INTEGRATION

### Objective

After model integration, implement authenticated create/retrieve, one typed Foundry provisioning function, operation dispatch through existing Celery/beat, and focused API/service/task/contract tests.

### Dependencies

- CLOUD-MODELS accepted by the orchestrator.
- Executable Foundry request/receipt shape in Task FOUNDRY-CONTRACT and its checked fixture.

### Owned Files Or Systems

- `backend/allies/api/`
- `backend/allies/services/`
- `backend/allies/gateways/`
- `backend/allies/exceptions.py`
- `backend/allies/tasks.py`
- `backend/allies/tests/` except `test_models.py`
- `backend/config/api.py`, `backend/config/openapi.py`, and the smallest necessary `backend/config/settings.py` additions
- `backend/pyproject.toml` coverage-source registration
- `docs/contracts/foundry-profile-provisioning-v1.json`

### Required Context

- Ponytail Full; reuse session, Workspace capability, HTTP, Celery, and API conventions.
- Repeat the original POST for retry. No retry endpoint/service/schema, outbox, gateway class, mTLS option, provider reference, speculative conversation record, or ticket-derived identifier.
- Add `POST /api/v1/onboarding/attempts`: require trusted origin plus CSRF-bound browser identity, reuse the existing greeting provider/admission/output-validation code without reading or writing a waitlist row, and persist one bounded opaque attempt.
- Add authenticated `POST /api/v1/workspaces/{workspace_id}/allies` and `GET /api/v1/workspaces/{workspace_id}/allies/{ally_id}`. The create request carries the attempt token, nonblank reply, and final seed fields; values must match the locked attempt.
- Separate HMAC digest of `Idempotency-Key` from canonical content fingerprint. Existing same-key/same-content operations replay even after attempt consumption; same-key/different-content conflicts without mutation.
- Add one typed stdlib HTTP `provision_profile()` function for `POST /api/v1/internal/profile-provisioning`, matching the Foundry fixture exactly. Use one shared service bearer and bounded response reads/timeouts; sanitize all errors.
- Dispatch due and expired-lease operations through existing Celery/beat. Perform external I/O outside DB transactions; duplicate/late delivery must converge via operation identity and matching receipts. Broker enqueue failure after commit must leave the truthful pending row and rely on beat.

### Acceptance Criteria

- Official onboarding issuance returns one opaque token and server-authored greeting without a waitlist record; raw token and handoff text never enter logs.
- Authenticated create atomically creates or replays one Ally/binding/operation and consumes/associates the attempt with its exact reply; cross-Workspace requests are indistinguishable 404s.
- Retrieve uses `select_related` and returns only Cloud-owned fields, binding identity, operation identity, and derived state.
- Same key/content replays, changed content returns 409, invalid/expired/foreign attempts fail closed, and no waitlist data is queried.
- Foundry pending/active/incompatible/malformed/timeout outcomes map truthfully; only active matching evidence marks binding bound.
- Celery claims are bounded and leased, expired leases recover, backoff is bounded, and operation expiry becomes repair-required without deleting durable rows.
- Focused tests cover service/API/task/contract/privacy behavior and at least the available database-level idempotency race evidence.

### Validation

- Run `make test APP=allies`, `make check`, and `make lint`; report any PostgreSQL-only test that cannot run locally.

### Required Result

- Files changed
- Tests and results
- Assumptions
- Blockers
- Integration notes

## Task FOUNDRY-CONTRACT

### Objective

Expose the existing idempotent `ensure_runtime_profile()` service through one private, service-bearer-authenticated v1 HTTP endpoint and verify the checked contract fixture.

### Dependencies

- Current Foundry `ensure_runtime_profile()` behavior is authoritative.
- A matching Foundry Workspace row already exists; Workspace infrastructure provisioning is not expanded in this task.

### Owned Files Or Systems

- Foundry worktree `E:\Users\Oluwatimilehin\Documents\Programming\helpers\allies-foundry\.forest\worktrees\profile-provisioning`
- `backend/runtime/api/register.py`
- `backend/runtime/api/schemas.py`
- `backend/config/settings.py`
- `backend/runtime/tests/test_profile_provisioning_api.py`
- `docs/contracts/foundry-profile-provisioning-v1.json`

### Required Context

- Ponytail Full; reuse `ensure_runtime_profile`, Ninja, existing bearer parsing style, and constant-time stdlib token comparison.
- Do not add models, migrations, gateway classes, auth configurability, provider references in receipts, new Workspace provisioning, or ticket-derived identifiers.
- Endpoint: `POST /api/v1/internal/profile-provisioning`.
- Request v1: `version`, bounded opaque Cloud `workspace_id`, `binding_id`, `ally_ref`, and `operation_id`, plus `request_fingerprint`, `job`, and exact `personality`.
- Resolve the existing Foundry Workspace by its opaque Cloud tenant correlation and derive the private profile UUID deterministically from `binding_id`; never return that UUID. Foundry authors a v1 first-chat instruction from `job` and uses the existing v1 OpenAI profile defaults. Appearance never crosses this boundary.
- Receipt v1 echoes `version`, `binding_id`, `operation_id`, and `request_fingerprint`, plus allowlisted `status` and `evidence_digest`; never return profile IDs, Hermes keys, credentials, seed payload, or raw exceptions.
- Accept only an `Authorization: Bearer` value matching `ALLIES_CLOUD_SERVICE_TOKEN`; require a strong token outside debug.

### Acceptance Criteria

- Exact replay is idempotent and changed seed conflicts without mutation.
- Missing/invalid bearer is indistinguishable `401` and does not expose the token.
- Missing Workspace and malformed/unknown-version input fail closed with bounded generic errors.
- Pending and active profile lifecycle states map truthfully; private identifiers and credentials are absent from receipt and captured errors.
- The one JSON fixture is exercised by tests.

### Validation

- Run focused Foundry API tests.
- Run `make check` and `make lint` if the focused slice is green.

### Required Result

- Files changed
- Tests and results
- Assumptions
- Blockers
- Integration notes
