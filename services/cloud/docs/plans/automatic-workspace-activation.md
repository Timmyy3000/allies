# Automatic Workspace Activation Plan

## Feature Overview

- Problem: Cloud already creates one idempotent personal Workspace, but the first Ally’s Foundry profile currently remains `pending`. Local live setup requires the operator to run `manage.py activate_fly_workspace`; staging runs only the Foundry API, so first-workspace Fly activation does not happen automatically.
- Target users: Authenticated Workspace owners creating their first Ally; operators recovering incomplete or legacy provisioning.
- Source docs/specs: The kickoff brief; Cloud `ENGINEERING_STYLE.md` and `docs/templates/PLAN_TEMPLATE.md`; Foundry `ENGINEERING_STYLE.md`; Nabu `foundry-continuity-layer`, `auth-account-foundation`, CLD-003, the engineering decision log, and the MVP roadmap.
- Success outcome: The first Ally request persists the exact Foundry Workspace/profile desired state and returns `pending` within the Cloud timeout. Existing Cloud retries then advance or resume the Fly lifecycle until profile materialization, after which Cloud binds the Ally. Existing safe-to-retry records can be repaired without new identities or duplicate provider resources.

## Scope

### In Scope

- `allies-foundry` registration that persists/resumes activation state and advances one bounded lifecycle step per Cloud retry, using the existing `WorkspaceLifecycle` and `FlyProvider` seams.
- Reuse of the same activation composition from the local management command.
- Cloud-side bounded retry/defer behavior and an explicit, dry-run-first repair operation for legacy 422/`foundry_rejected` records.
- Staging/production configuration, contract tests, recovery tests, and a staged live proof.

### Out of Scope

- A new shared Railway runtime, queue, or Foundry worker/scheduler. The existing Cloud worker remains the durable retry boundary and Foundry’s lifecycle remains the provider-side resume mechanism.
- Changes to personal Workspace creation, Ally identity, binding identity, conversation identity, or existing Foundry lifecycle invariants.
- Automatic reset of arbitrary `repair_required` records, provider-wide cleanup, or bulk Fly deletion.
- `allies-interface` changes unless review proves the existing provisioning-state view cannot represent the recovery result.

### Dependencies and Assumptions

- Cloud’s existing `create_ally` post-commit enqueue and Celery beat `dispatch_due_provisioning` remain the durable retry boundary; the broker failure must continue to leave the committed operation recoverable.
- Foundry profile provisioning remains version `1`; activation is a separate authenticated call and its response exposes only `pending` or `active`. Cloud treats timeout/202 as retryable.
- Foundry remains the owner of Fly apps, Volumes, Machines, runtime credentials, profiles, and generation fencing. Cloud never imports Foundry models or recreates Fly orchestration.
- The existing local activation command is evidence of the required topology, not a production credential-delivery implementation.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| Foundry `backend/runtime/services/workspaces.py` | `advance_workspace_activation` (minimal addition to the existing lifecycle service) | `advance_workspace_activation(workspace_id: UUID \| str, spec: WorkspaceSpec, deadline: float) -> WorkspaceBinding \| None` | Registered Workspace and validated deployment spec; perform at most one resumable provider phase and stop before the caller’s remaining request budget is exhausted | Existing binding when idle, otherwise a pending/unfinished result | Reuses the existing Workspace row claim, phase transitions, deterministic provider names, ownership checks, and provider adapter; never starts a second operation or runs the full topology in one Cloud request |
| Foundry `backend/runtime/api/register.py` | `profile_provisioning` | Existing `POST` handler | Authenticate Cloud service; validate existing v1 payload; register/replay the Cloud Workspace and exact profile identity; use the remaining request budget for one activation step only | Existing receipt, normally `pending` until workspace/profile materialization completes | Persist desired Workspace/profile state before provider work; return within the Cloud timeout; later exact Cloud retries advance the durable lifecycle. A successful activation step may still return `pending` until `allies-runtime` sends the existing materialization receipt |
| Cloud `backend/allies/services/provisioning.py` | `dispatch_due_provisioning` | Existing `dispatch_due_provisioning(*, now=None, limit=20) -> DispatchReport` | Preserve lease, attempt fence, expiry, max backoff, and bounded batch behavior | Existing report | Treat Foundry `pending` as retryable; treat transport/5xx as retryable; never mark a binding `BOUND` until the receipt is `active` |
| Cloud `backend/allies/services/provisioning_recovery.py` (new) | `plan_or_requeue_legacy_operations` | `plan_or_requeue_legacy_operations(*, workspace_id: UUID, operation_id: UUID \| None, error_code: str, confirm: bool = False) -> RecoveryReport` | Require explicit Workspace, optional exact operation, and allowlisted legacy error code; default is dry run | Sanitized matched/already-requeued IDs and counts | Under one transaction and `select_for_update`, atomically transition only `REPAIR_REQUIRED + foundry_rejected` to `RETRYABLE`, clear `completed_at`, `lease_expires_at`, and `last_attempt_at`, set `next_attempt_at=now`, preserve `attempt_count`/identity/fingerprint, and no-op safely on repeated/concurrent requests |

### API and Transport Contracts

| Consumer | Method and path / event | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Cloud gateway | Existing `POST /api/v1/internal/profile-provisioning` | Foundry validates the existing Cloud service bearer | Existing v1 `workspace_id`, `binding_id`, `ally_ref`, `operation_id`, fingerprint, and Ally seed | Existing receipt: `status: pending\|active\|cleanup_pending\|deprovisioned\|repair_required`; no private Fly/profile identifiers | `401` invalid credential; `422` invalid request; `409` identity/conflict; bounded transport/5xx is retried by Cloud with the same operation identity |
| Cloud operator | New `repair_provisioning` management command | Local/operator access only; no public HTTP endpoint | Explicit `--workspace-id`; optional `--operation-id`; required `--error-code foundry_rejected`; dry-run default; `--confirm` required for mutation | Sanitized report of matched IDs, current states, and intended transition | Refuse missing scope, unknown code, incompatible binding, or ambiguous provider state; repeated `--confirm` sees `RETRYABLE` and reports already requeued without mutating again |

Representative existing request/response (shape unchanged):

```json
{
  "version": 1,
  "workspace_id": "<cloud-workspace-uuid>",
  "binding_id": "<cloud-binding-uuid>",
  "ally_ref": "<cloud-ally-uuid>",
  "operation_id": "<cloud-operation-uuid>",
  "request_fingerprint": "<64-hex-digest>",
  "name": "Mira",
  "job": "Study partner",
  "personality": "Calm"
}
```

```json
{
  "version": 1,
  "binding_id": "<cloud-binding-uuid>",
  "operation_id": "<cloud-operation-uuid>",
  "request_fingerprint": "<64-hex-digest>",
  "status": "pending",
  "evidence_digest": "<64-hex-digest>"
}
```

`pending` is honest while the Fly Machine/runtime materializes the profile. Cloud keeps the Ally non-bound and retries through the existing bounded backoff. `active` is the only receipt that promotes the binding.

### Data Shapes and Invariants

#### Database Models

| Type / category | Model / table | Location | Fields and types | Required / nullable / defaults | Validation, indexes, constraints, and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- | --- |
| Persisted model / table | Existing `Workspace` | Foundry `backend/runtime/models.py` | Existing provider refs, generation, provisioning phase/claim fields | Existing null/unbound and complete-idle invariants | Keep row locking, resumable phases, generation fencing, ownership checks, and no silent replacement | No migration expected unless implementation proves an operation field is missing |
| Persisted model / table | Existing `RuntimeProfile` | Foundry `backend/runtime/models.py` | Existing lifecycle/materialization fields | Existing `pending -> active` receipt contract | No duplicate profile for the deterministic profile ID; no overwrite on seed mismatch | No migration expected |
| Persisted model / table | Existing `ProvisioningOperation` and `AllyBinding` | Cloud `backend/allies/models.py` | Existing status, lease, attempt, fingerprint, receipt, and binding fields | Preserve existing statuses and one-way identity | Repair only explicitly scoped legacy records; do not recreate or rebind | Additive migration only if a durable repair audit field is demonstrated necessary |

#### Enums

No enum change is planned. Existing Foundry workspace phases/profile states and Cloud provisioning states remain the compatibility vocabulary.

#### API Request Schemas

The existing profile request is unchanged. The new internal activation request is exactly `{version: 1, workspace_id}` and uses the existing Cloud service token.

#### API Response Schemas

No response field change is planned. Validate that the existing receipt remains sanitized and that `pending`/`active` transitions are truthful after activation is added.

#### Temporary / Internal Shapes

- Activation configuration/spec: deployment-owned, non-persisted shape built from validated settings and opaque credential references; never log raw tokens.
- Recovery report: operator-only counts/opaque UUIDs and safe error codes; never include provider responses, secrets, or personal seed text.

#### Service Primitives

No parallel activation abstraction is planned. Extend the existing `runtime.services.workspaces.WorkspaceLifecycle` only as needed for one bounded phase advance; the management command and API call the same existing lifecycle/provider seam and must not bypass its transactions, locks, phase deadlines, or ownership checks.

## Phases

### Phase 1 - Foundry automatic activation

- Goal: Make profile provisioning explicitly trigger the existing Foundry Fly activation path.
- Work items:
  - Add the authenticated activation endpoint and route it through the existing management-command composition, which already uses the resumable `WorkspaceLifecycle` and `FlyProvider` seams.
  - Call activation from the Cloud worker after the profile request. Return `pending` on timeout/partial provider outcomes; exact Cloud retries resume the same Foundry Workspace.
  - Keep the local management command as an operator composition of the same lifecycle/provider seam. It may run the full local procedure because it is not behind Cloud’s 5-second request, but it must retain existing idempotent recovery safeguards.
  - Keep profile creation/materialization idempotent and ordered so a new or replayed request cannot create a second profile, Machine, Volume, credential, or generation.
  - Update settings/env inventories and operational docs with the release prerequisite contract below.
- Impacted files/systems: Foundry `backend/runtime/services/workspaces.py`, `backend/runtime/api/register.py`, `backend/runtime/management/commands/activate_fly_workspace.py`, `backend/config/settings.py`, `.env`/deployment inventory, `docs/operations/local-fly-docker.md`, `docs/operations/staging.md`, and targeted Foundry tests.
- Exit criteria: the API persists desired state and returns within the Cloud timeout; repeated Cloud retries advance/resume the exact lifecycle; the local command remains a compatible operator fallback; profile receipt is `pending` until the existing materialization receipt makes it `active`.

### Phase 2 - Cloud recovery and contract hardening

- Goal: Let existing Cloud operations converge automatically and provide a safe repair path for the known legacy terminal state.
- Work items:
  - Preserve the current Celery task/beat path and add tests for activation-triggering profile calls, pending deferral, transport retry, expired leases, duplicate dispatch, and active-only binding.
  - Add a dry-run-by-default `repair_provisioning` command for only `status=REPAIR_REQUIRED AND safe_error_code=foundry_rejected` (the known legacy 422 contract failure).
  - Require exact Workspace scope, optional exact operation ID, the explicit `foundry_rejected` code, and `--confirm` for mutation. In one `transaction.atomic()` block, lock the operation and binding, verify the record still matches the requested scope and binding/Ally identity, then transition `REPAIR_REQUIRED -> RETRYABLE`, clear `completed_at`, `lease_expires_at`, and `last_attempt_at`, set `next_attempt_at=now`, and preserve `attempt_count`, `receipt_digest`, operation ID, binding ID, Ally ID, and fingerprint. A concurrent or repeated request observes the already-`RETRYABLE` row and performs no second transition.
  - Exclude `stored_ally_invalid`, onboarding-handoff repair, incompatible bindings, unknown codes, and ambiguous provider state. Print only sanitized IDs/counts and the intended state change.
  - Document that replaying the same Cloud operation recovers an existing Foundry Workspace/profile; it does not create a new identity.
- Impacted files/systems: Cloud `backend/allies/services/provisioning.py`, new `backend/allies/services/provisioning_recovery.py`, new management-command package/file under `backend/allies/management/commands/`, `backend/allies/tasks.py` only if enqueue wiring is needed, `backend/config/settings.py`, `docs/operations/railway-staging.md`, and Cloud tests.
- Exit criteria: dry run identifies only intended records; confirmed repair performs the atomic transition exactly once; normal Cloud dispatch replays the same Foundry request, advances activation, and reaches `pending`/`active` without duplicate records.

### Phase 3 - Integrated staging proof and rollout

- Goal: Prove the first-account/first-Ally path in the API-only Foundry staging topology and release with a reversible gate.
- Work items: deploy Foundry configuration and Cloud code in dependency order; verify Cloud web/worker/beat and Foundry Railway API/Postgres; record the owner-approved Hermes and `allies-runtime` image sources plus exact immutable digests; create one fresh account and first Ally; observe bounded `pending` responses and Cloud retry progression; verify one Fly App/Volume/Machine generation with Hermes plus `allies-runtime`, runtime materialization, Cloud binding, a forced timeout, and exact replay; run the scoped dry-run against legacy records before any confirmed repair.
- Impacted files/systems: Cloud Railway web/worker/beat, Foundry Railway API/Postgres, Fly provider resources, and optional Interface read-only verification.
- Exit criteria: sanitized evidence proves Cloud web/worker/beat and Foundry Railway API/Postgres are on the intended revisions; the exact approved image digests are recorded; one Cloud Workspace maps to one Foundry Workspace and one Fly App/Volume/Machine generation; Hermes plus `allies-runtime` materialize one profile; truthful `pending -> active -> bound` transitions occur; no operator activation command is used; a forced timeout is recovered by the same operation; and exact replay creates no duplicate records/resources.

## Acceptance Criteria

1. A new account still receives exactly one personal Cloud Workspace.
2. Creating its first Ally persists Foundry activation state without running the full Fly topology inside Cloud’s 5-second request; Cloud retries advance/resume the exact per-Workspace Fly App, Volume, and two-container Machine once, without an operator command.
3. The Ally remains pending/non-bound until Foundry reports an active/materialized profile; Cloud never converts a `pending` receipt into success, including after a request timeout.
4. Existing Cloud pending/retryable operations and Foundry partial lifecycle phases resume through the same idempotent path.
5. Known legacy 422/`foundry_rejected` records can be dry-run inspected and explicitly requeued without changing Ally, binding, operation, or fingerprint identity; unrelated repair states are untouched.
6. Repeated requests, concurrent Cloud dispatches, provider timeouts, partial resource creation, stale claims, and ambiguous outcomes are bounded and do not create duplicate provider resources or generations.
7. Cloud and Foundry contract tests plus the documented staging proof pass, with no secrets/private runtime identifiers in responses or logs.

## Backend Considerations

### Query Optimization Plan

- Existing hot paths are one Cloud operation claim and one Foundry Workspace/profile lookup. Use existing `select_related`/row locks; keep repair selection indexed by status/error/scope where the database proves a need.
- Do not enumerate all tenants or profiles in the request. Recovery is bounded by explicit Workspace/operation scope and a maximum batch only if a later reviewed operator workflow requires it.

### N+1 Prevention

- Cloud dispatch keeps its current `select_related("workspace", "binding__ally")` shape.
- Foundry activation loads the one Workspace and exact profile; runtime reconciliation remains the existing bounded workspace projection.
- Add query-count assertions only around any new recovery/report query.

### Detailed Unit Test Cases

- Foundry: API activation on missing Workspace; exact replay; concurrent replay; partial phase resume; existing idle binding; missing/unsafe settings; provider timeout/ambiguous result; ownership/attachment conflict; generation/credential fencing; profile remains pending before materialization and becomes active after the existing receipt.
- Cloud: first Ally dispatch reaches Foundry; pending defers; 5xx/timeout defers; active binds once; duplicate task claims are fenced; expired lease recovers; legacy repair dry run and confirmed requeue; wrong Workspace, wrong error code, incompatible binding, and already-requeued operation are rejected/no-op.
- Interface: no implementation test unless the existing client cannot render the current `provisioning_state`/`retryable` contract.

## Test Plan

- Cloud focused: `make test APP=allies/tests/test_provisioning.py`, `make test APP=allies/tests/test_foundry_gateway.py`, plus the new recovery test module; then `make check`, `make lint`, and the relevant API/contract tests.
- Foundry focused: `make test APP=runtime/tests/test_profile_provisioning_api.py`, `make test APP=runtime/tests/test_workspace_lifecycle.py`, `make test APP=runtime/tests/test_activate_fly_workspace_command.py`; then `make check`, `make validate`, `make lint`, and `make runtime-test` if runtime image/client code changes.
- Integration/manual: run the existing local activation procedure as a fallback comparison, then prove the same first-Ally flow through Cloud against Foundry staging without manually invoking activation; inspect exact recorded resources before any cleanup.
- Migration check: run `make check`; if models change, generate with the repository’s `make migrations APP=<app>` command and review the migration before applying it.

## Deployment, Rollout, and Rollback

- Release prerequisite contract, with values intentionally unset and owned by the Cloud/Foundry platform owner:

  | Contract item | Required release decision/evidence |
  | --- | --- |
  | Foundry Railway process/service | The existing Foundry Railway **API service** backed by Foundry Postgres, deployed from `/backend` and serving `/api/v1/internal/profile-provisioning`; no separate worker/scheduler is assumed. If one-phase API advancement cannot meet the budget, the owner must approve the smallest single `foundry-activation-worker` service/task and its deployment process before implementation. |
  | Cloud Railway processes | Existing Cloud `web`, `worker`, and singleton `beat` services; `worker` consumes the `cloud` queue and `beat` dispatches `allies.dispatch_due_provisioning`. |
  | Foundry secret/config names | `ALLIES_CLOUD_SERVICE_TOKEN`, `FLY_API_TOKEN`, `FLY_ORG`, `FLY_REGION`, `HERMES_IMAGE`, `RUNTIME_IMAGE`, `FOUNDRY_ORIGIN`, `PROFILE_PROVISIONING_PROVIDER`, `PROFILE_PROVISIONING_MODEL`, `PROFILE_PROVISIONING_BASE_URL`, `PROFILE_PROVISIONING_CREDENTIAL_NAME`, and `PROFILE_PROVISIONING_CREDENTIAL_REF`; raw values remain in Railway’s secret/config store. |
  | Cloud secret/config names | `ALLIES_FOUNDRY_URL`, `ALLIES_FOUNDRY_SERVICE_TOKEN`, `ALLIES_FOUNDRY_TIMEOUT_SECONDS`, `CACHE_URL` or explicit `CELERY_BROKER_URL`, and the existing auth/deployment settings. |
  | Image source and digest policy | Owner names the approved Hermes and `allies-runtime` image sources and records immutable `@sha256:<digest>` references for each environment. Mutable tags are forbidden; do not invent or copy digest values into the plan. |
  | Fly placement | Owner confirms the exact Fly organization slug and region values for `FLY_ORG` and `FLY_REGION`; they must be allowed by the token and match the existing per-Workspace naming/provider policy. |
  | Runtime credential delivery/rotation | Foundry issues a generation-scoped bearer, stores only its digest, delivers it to `allies-runtime` through the approved Fly file-secret/resolver boundary, revokes the retired generation after authoritative stop, and proves rotation on replacement. The production resolver/secret names and owner are not yet approved. |
  | Network reachability | Cloud reaches Foundry over the validated HTTPS `ALLIES_FOUNDRY_URL`; each Fly Machine reaches the public HTTPS `FOUNDRY_ORIGIN` outbound; the tenant Machine exposes no public service. Owner supplies DNS/TLS/egress proof for staging and production. |
  | Kill switch | Add `ALLIES_FOUNDRY_AUTO_ACTIVATION_ENABLED=false` as the default. Enable only after staging proof and owner approval; disabled mode preserves registration/profile `pending` and the documented manual recovery path. |
  | Decision owner | Named Cloud/Foundry platform owner approves the complete contract, values, secret storage, image provenance, and enablement date. |

- Roll out Foundry API/lifecycle code and configuration first, then Cloud worker/beat/web. Keep automatic activation disabled by default until one staging proof passes; existing profile provisioning remains available with truthful `pending` when the gate is off.
- Before repair, run the command in dry-run mode, capture sanitized counts/IDs, and approve only the known legacy error-code scope. Re-run the normal Cloud dispatcher after confirmation.
- Rollback: disable automatic activation at the Foundry configuration gate and stop the Cloud worker/beat rollout if needed. Do not reset records or delete Fly resources. Existing partial phases remain resumable; rerun the documented exact-workspace activation/recovery path after the prerequisite is fixed. For an intentionally abandoned test, use the existing exact-ID local rollback procedure and retain the Foundry Workspace row.

## Unresolved Owner Decisions

- Approve the release prerequisite contract above, especially production generation-scoped runtime credential delivery/rotation, exact secret-store ownership, image sources/digests, Fly organization/region, and HTTPS reachability.
- Confirm that the one-phase `WorkspaceLifecycle` API seam meets the Cloud request budget. If not, explicitly approve the minimal Foundry activation task/worker and its Railway process; do not introduce it silently.
- Confirm the activation kill-switch owner and enablement gate. No Interface change is required unless code evidence shows the current `provisioning_state`/`retryable` response cannot represent the recovery state.

## Risks and Mitigations

- Risk: A provider phase still exceeds the Cloud request budget. Mitigation: one-phase advancement with a hard remaining-deadline check; stop and retry without guessing. Add a single task/worker only after owner approval if the existing seam cannot fit.
- Risk: Automatic activation has no approved production secret/image delivery. Mitigation: fail closed before provider I/O; treat the release contract as a blocker; do not reuse proof-only credentials by assumption.
- Risk: concurrent first Ally requests race on one Workspace. Mitigation: existing Workspace row lock, deterministic names, lifecycle phases, and idempotent profile identity.
- Risk: broad repair resets corrupt valid terminal states or duplicates resources. Mitigation: dry-run default, explicit Workspace/operation scope, allowlisted legacy code, matched-state checks, and no provider-wide cleanup.
- Risk: an active Fly Machine exists but profile materialization remains pending. Mitigation: preserve truthful pending state, let runtime reconciliation complete, and alert on bounded age rather than binding early.
