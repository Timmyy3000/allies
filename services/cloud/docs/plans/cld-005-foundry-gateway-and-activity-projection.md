# CLD-005 Foundry gateway and Cloud activity projection plan

## Feature Overview

- Problem: CLD-004 accepts a durable Cloud `Message`, but Cloud has no dispatch receipt or safe projection boundary for Foundry execution. The existing `allies.gateways.foundry` module is profile-provisioning-only.
- Target users: Signed-in Workspace owners using one continuous conversation per Ally; operators need recoverable dispatch and sanitized evidence.
- Source docs/specs: Accepted Nabu specification `projects/allies/engineering/specs/cld-005-foundry-gateway-and-activity-projection.md`; Cloud `docs/architecture/cloud-domain-map-and-contract.md`; Cloud backend guide; Foundry FND-007 services/models and API; CLD-004 and FND-007 handoffs.
- Success outcome: Every accepted Cloud message has one durable execution intent, exact retries are idempotent, safe Foundry events become ordered Cloud activities for the owning conversation, and no public surface exposes runtime authority.

## User Stories

1. As a Workspace owner, I want an accepted message to remain visible while Foundry dispatch is pending, so a timeout never looks like lost or completed work.
2. As a Workspace owner, I want safe assistant/activity updates and truthful terminal states, so the conversation reflects durable runtime evidence without provider or runtime secrets.
3. As an operator, I want duplicate, timeout, authorization, sequence-gap, and partial-failure evidence, so ambiguous work can be reconciled without starting a second Hermes turn.

## Scope

### In Scope

- Cloud gateway/dispatch integration against the merged CLD-004 `Message` contract, plus the CLD-005 activity projection/read boundary and tests. CLD-004 model/controller implementation is not repeated here.
- Cloud gateway adapter for versioned HTTPS/JSON execution command and reconciliation lookup.
- Authenticated Foundry event intake and projection with canonical fingerprints, composite event identity, sequence validation, bounded safe payloads, and monotonic terminal state.
- Foundry command/event contract publication, execution correlation, event publication/outbox, reconciliation lookup, and contract fixtures/tests.
- Strict v1 compatibility with shared fixtures and unknown-version rejection, bounded timeout/retry policy, sanitized observability, and staging contract evidence. A future v2 rollout must define an explicit compatibility window and migration before parser broadening.

### Out of Scope

- CLD-006 cursor replay, reconnect streaming, stop, user retry, or terminal repair UX.
- CLD-004 conversation/message acceptance, models, controllers, send-key semantics, and migrations; they are already merged in the `bef7278` baseline and are consumed without reimplementation.
- The UUID reset/cutover, waitlist preservation proof, removal of the prefixed `public_id` layer, and CLD-004 ancestry proof; `bef7278` is satisfied foundation evidence, not CLD-005 implementation or validation scope.
- Direct Interface-to-Foundry calls, tool approval completion, attachments, billing, routines, or multiple conversations per Ally.
- Reimplementation of Foundry leases, Machines, Hermes sessions, or runtime execution.

### Dependencies and Assumptions

- CLD-004 remains the owner of accepted message creation and caller send-key semantics. Its merged model surface is `Conversation` plus `Message`; CLD-005 uses the accepted user `Message.id` as the stable business/dispatch identity and immutable `Message.sequence` as `conversation_turn_ordinal`, and must not add a parallel `ExecutionIntent` model.
- FND-007 remains the owner of execution/attempt/event truth and effective session update before completion.
- Cloud `bef7278` is the UUID-native baseline: all CLD-005 primary and foreign keys use UUIDs, public APIs/correlation use those UUIDs directly, and CLD-005 must not add a parallel `public_id` layer. `AllyBinding.cloud_binding_id` remains a UUID contract field. The accepted `Message.sequence` is the immutable `conversation_turn_ordinal` included in the command fingerprint.
- Foundry execution/attempt/lease/profile/event UUIDs remain Foundry-private; they are never exposed as Cloud identifiers.
- Existing route/settings evidence fixes the v1 names: Foundry command creation is `POST /api/v1/internal/executions`, reconciliation is `GET /api/v1/internal/executions/reconcile`, and Cloud event intake is `POST /api/v1/internal/foundry/events`. Cloud reuses `ALLIES_FOUNDRY_URL`, `ALLIES_FOUNDRY_SERVICE_TOKEN`, and `ALLIES_FOUNDRY_TIMEOUT_SECONDS`; Foundry validates commands with `ALLIES_CLOUD_SERVICE_TOKEN`. Event delivery uses a distinct direction-scoped bearer and never returns or logs either credential.
- Django migrations are generated with `make migrations APP=<app>` and inspected, never hand-written.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `backend/chat` (CLD-004 integration hook) | `dispatch_accepted_message` | `dispatch_accepted_message(message: Message) -> DispatchReceipt` | Consume one accepted queued user `Message`; use its UUID and immutable sequence; do not create/modify conversation acceptance or add an intent model | Existing UUID message ID plus gateway dispatch state | Post-commit task claims the message-linked dispatch row; typed 404/409/422 for missing/conflicting contract |
| `backend/activities/services/projection.py` | `project_foundry_event` | `project_foundry_event(envelope: FoundryEventEnvelope) -> ProjectionResult` | Authenticate gateway first; validate v1 envelope/fingerprint, scope/binding/message correlation, composite identity, attempt sequence, allowlisted payload and size | `applied`, `duplicate`, or held/rejected result | Transaction locks conversation/message feed, writes immutable receipt/activity, advances last contiguous sequence and monotonic product state |
| `backend/allies/gateways/foundry.py` | `create_execution_intent` | `create_execution_intent(command: ExecutionCommand) -> ExecutionReceipt` | Exact request body/key/fingerprint only; HTTPS origin, bounded timeout/body, no redirects; strict v1 and unknown-version rejection | Accepted/duplicate/conflict/not-found/invalid receipt; private Foundry refs remain adapter-only | Network call; maps 2xx/4xx/5xx/timeout to typed gateway outcomes without leaking response bodies |
| `backend/allies/gateways/foundry.py` | `reconcile_execution_intent` | `reconcile_execution_intent(idempotency_key, fingerprint) -> ReconciliationReceipt` | Read-only lookup, same key/fingerprint, bounded timeout | `accepted`, `not_found`, or `conflict` | Never creates execution; retryable transport outcome remains reconciliation-needed |
| `backend/chat/tasks.py` | `dispatch_pending_messages` | Celery task `(limit: int = 20) -> DispatchReport` | Claims message-linked dispatch rows with a 60-second lease, max 5 dispatch attempts, exponential backoff `min(300s, 2^(attempt-1))` plus bounded 0–25% jitter | Counts claimed/accepted/deferred/exhausted/reconciled | Calls adapter after commit; exact retry only; unknown outcome reconciles before another request; exhaustion enters `reconciliation_needed` |

### API and Transport Contracts

| Consumer | Method and path / event | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Cloud gateway | `POST /api/v1/internal/executions` | Foundry validates Cloud service bearer; derives Workspace/profile from immutable binding and its own records | `ExecutionCommand` below | `ExecutionReceipt` with status and opaque private ref only inside gateway | `401` invalid credential; `409` conflict; `422` invalid; `404` privacy-safe binding denial; `503/504` unknown outcome; exact retry/reconcile only |
| Cloud gateway | `GET /api/v1/internal/executions/reconcile?idempotency_key=...&fingerprint=...` | Same bearer; read-only lookup | Query key and canonical fingerprint, bounded lengths | `ReconciliationReceipt` (`accepted`, `not_found`, `conflict`) | `401`, `409`, `422`, `503`; no side effect and no auto-create |
| Foundry event publisher | `POST /api/v1/internal/foundry/events` | Cloud validates Foundry service bearer; re-checks Workspace/Ally/conversation/binding on receipt | `FoundryEventEnvelope` below | `202 {event_id, status: applied\|duplicate}` | `401`, `404` privacy-safe, `409` identity/sequence conflict, `422` invalid/oversize; publisher retries exact envelope only |
| Cloud product API | `POST /api/v1/workspaces/{workspace_id:uuid}/conversations/{conversation_id:uuid}/messages` | Current Cloud session plus conversation capability | Existing CLD-004 `{content}` body plus `Idempotency-Key` header | Standard `{status,message,data}` with UUID message ID and product state | `401/403/404/409/422`; accepted response never claims completion |
| Cloud product API | `GET /api/v1/workspaces/{workspace_id:uuid}/conversations/{conversation_id:uuid}/activities` | Current Workspace membership/capability rechecked on every read | Bounded snapshot read with `limit<=200`; no cursor/replay/reconnect semantics in CLD-005 | Activities with UUID activity/sequence owner IDs, safe text/kind, product state, and last-contiguous sequence metadata | Foreign resource returns privacy-safe `404`; no Foundry IDs |

Representative command:

```json
{
  "schema_version": "v1",
  "kind": "execution.command",
  "producer": "cloud",
  "service_identity": "cloud-service",
  "command_id": "550e8400-e29b-41d4-a716-446655440000",
  "idempotency_key": "650e8400-e29b-41d4-a716-446655440000",
  "scope": {"kind": "workspace", "cloud_workspace_id": "750e8400-e29b-41d4-a716-446655440000"},
  "conversation_turn_ordinal": 12,
  "cloud": {"ally_id":"850e8400-e29b-41d4-a716-446655440000","conversation_id":"950e8400-e29b-41d4-a716-446655440000","message_id":"a50e8400-e29b-41d4-a716-446655440000","cloud_binding_id":"c50e8400-e29b-41d4-a716-446655440000"},
  "source_kind": "conversation_message",
  "payload": {"kind":"execution_input","text":"normalized user text"},
  "issued_at": "2026-08-25T12:00:00Z",
  "deadline_at": "2026-08-25T12:00:05Z",
  "fingerprint": "canonical-json-sha256:v1:<64 lowercase hex>"
}
```

Representative event:

```json
{
  "schema_version":"v1","kind":"execution.event","producer":"foundry","service_identity":"foundry-service",
  "event_id":"d50e8400-e29b-41d4-a716-446655440000","event_dedupe_key":"execution:attempt:generation:event",
  "scope":{"kind":"workspace","cloud_workspace_id":"750e8400-e29b-41d4-a716-446655440000"},
  "cloud":{"ally_id":"850e8400-e29b-41d4-a716-446655440000","conversation_id":"950e8400-e29b-41d4-a716-446655440000","message_id":"a50e8400-e29b-41d4-a716-446655440000","cloud_binding_id":"c50e8400-e29b-41d4-a716-446655440000"},
  "conversation_turn_ordinal":12,
  "foundry":{"execution_id":"e50e8400-e29b-41d4-a716-446655440000","attempt_id":"f50e8400-e29b-41d4-a716-446655440000","generation":3,"attempt_sequence":7},
  "event_type":"message.delta","payload":{"kind":"assistant_delta","text":"safe bounded fragment"},
  "issued_at":"2026-08-25T12:00:01Z","fingerprint":"canonical-json-sha256:v1:<64 lowercase hex>"
}
```

Canonical fingerprint rules are shared by both repositories: NFC strings, sorted keys, compact JSON, ASCII escaping, `allow_nan=false`, UTF-8 SHA-256, and the `canonical-json-sha256:v1:` label. `issued_at`, `deadline_at`, transport headers, and receipt timestamps are excluded from the stable projection. The immutable serialized envelope is the sole fingerprint source; persisted receipts store that envelope fingerprint and never derive a second delivery fingerprint. Unknown schema versions/kinds fail closed. A future v2 rollout must publish a new fixture, compatibility window, and migration plan before accepting another version.

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `Conversation`, `Message` | `backend/chat/models.py` on merged `bef7278` | UUID primary keys/FKs, accepted message state, immutable `Message.sequence`, content fingerprint, and send-key scope; `Message.id` is the dispatch identity | Sequence is allocated transactionally once under the conversation lock; never derived from arrival order or Foundry attempt sequence | CLD-004 remains sole owner of acceptance/idempotency; CLD-005 adds only message-linked dispatch/projection state | No `ExecutionIntent`, identity-reset, or CLD-004 migration in CLD-005 |
| `Activity` | `backend/activities/models.py` | UUID primary key/FKs to conversation/message, Foundry `generation`, `attempt_id`, `attempt_sequence`, stable event UUID, deterministic ordering key, kind, bounded safe payload/text, source state, fingerprint, created_at | Each accepted event maps to `(message.sequence, generation, attempt_id, attempt_sequence, stable_event_id)`; only the current generation for a turn is valid; product sequence allocation is transactional | Allocate one next product sequence under a conversation/counter lock only after identity/turn validation; retries reuse it; stale generations and premature later turns are held | Additive CLD-005 migration on the UUID-native baseline; immutable receipts follow existing retention policy |
| `DispatchOutbox` | `backend/chat` | One-to-one UUID FK to accepted user `Message`, immutable canonical UTF-8 command bytes/blob, byte length, SHA-256/fingerprint, delivery state, attempt count, lease, next attempt, safe error code, timestamps | Created for the accepted message after commit; state `pending` default; no raw provider response/token | Transmit stored bytes directly on every retry/restart; no DTO reserialization or changed fingerprint; command budget is max 5 attempts | Additive CLD-005 migration; cascade with the owning message/conversation/account policy; cleanup is idempotent and privacy-reviewed |
| `ExecutionCommand`, `ExecutionReceipt`, `FoundryEventEnvelope` | `backend/allies/gateways/contracts.py` | Typed Pydantic DTOs mirroring JSON above, including immutable `conversation_turn_ordinal` | `extra=forbid`, strict strings/ints, bounded text, lowercase digest | Reject unknown fields, private authority from caller, malformed digest, oversized payload, unknown version, or ordinal mismatch; fingerprint covers the ordinal and every event must echo it unchanged | Strict v1 fixture now; future v2 compatibility requires an explicit rollout artifact |

### Frontend Interaction Shapes (if applicable)

Interface is out of scope. Cloud exposes only UUID product identifiers, product states, bounded activity text/kind, and last-contiguous sequence metadata from a bounded snapshot read; CLD-006 owns cursor/replay/reconnect semantics. No Foundry/Hermes/Fly identifier or gateway credential crosses this boundary.

## Phases

### Phase 1 - Publish the joint contract and Foundry command boundary

- Goal: Make strict v1 command, receipt, reconciliation, event envelope, fingerprint, authentication, and privacy rules executable in Foundry without changing runtime truth ownership.
- Work items: Add strict DTOs and canonical serializer; extend execution correlation fields and constraints; add `POST /api/v1/internal/executions` and read-only reconciliation endpoint; map Cloud binding to Foundry Workspace/profile; return accepted/duplicate/conflict/invalid/privacy-safe unavailable; add contract fixture and service/API tests.
- Impacted files/systems: Foundry `backend/runtime/api/schemas.py`, `register.py`, `models.py`, `services/executions.py`, new contract/dispatch modules, migration, `docs/contracts/` fixture, runtime tests.
- Exit criteria: Fake-provider-free tests prove exact replay, conflicting fingerprint, unknown kind/version, cross-workspace binding denial, bounded text, and no private runtime identifiers in response serializers/logs.

### Phase 2 - Add the Cloud dispatch adapter

- Goal: Consume an accepted CLD-004 user `Message` without recreating its model/controller, then turn it into one durable post-commit command with lost-response reconciliation.
- Work items: Add only the adapter hook/task and message-linked dispatch outbox; derive command/idempotency identity from `Message.id` and turn ordinal from `Message.sequence`; add strict gateway DTOs, 5-second timeout/body/redirect guards, established service-token settings, 60-second task lease, max 5 attempts, `min(300s,2^(attempt-1)) + 0–25% jitter`, and an exhausted `reconciliation_needed` operator receipt. No new acceptance/intent model, CLD-004 rewrite, identity-reset migration, or cutover validation.
- Impacted files/systems: Cloud `backend/allies/gateways/foundry.py` and contract module, `backend/chat/tasks.py` plus additive dispatch migration, `backend/config/settings.py`, and gateway/task tests.
- Exit criteria: Existing CLD-004 message is dispatched once; exact gateway retry returns the original receipt; timeout reconciles before retry; max-attempt exhaustion records operator-reconcilable state; unknown outcome remains non-terminal and no second command is emitted.

### Phase 3 - Add Cloud activity projection and Foundry event publication

- Goal: Deliver normalized Foundry events into the owning Cloud conversation safely and in order.
- Work items: Add `activities` app, immutable event receipt/activity models, projector and authorized bounded snapshot read API; add Foundry publication/outbox row created with event append and bounded retry task; use wire kind `execution.accepted` (the accepted Nabu vocabulary). If FND-007 emits internal `execution.dispatched`, Foundry translates it to `execution.accepted` at the contract publisher and Cloud accepts only `execution.accepted` on the wire. CLD-004 allocates one `conversation_turn_ordinal` transactionally when each accepted message/intent is created or claimed; retries retain the same attempt identity/ordinal, while a fresh attempt is valid only as an explicit newer generation. The ordinal is signed/fingerprinted in the command and echoed unchanged by every event. Cloud orders valid events by `(conversation_turn_ordinal, generation, attempt_id, attempt_sequence, stable_event_id)`; attempt/generation identity prevents two fresh attempts with sequence 1 from colliding, and stale generations are rejected before ordering. Within a turn, missing sequences produce held/retryable `sequence_gap`; a new turn arriving before prior terminal evidence is held and cannot advance projection. After identity and turn checks, allocate one Cloud product sequence under a conversation/counter lock and commit activity plus counter atomically; duplicates reuse existing mapping. Concurrent turns for one Ally serialize on the lock, while different Allies/conversations proceed independently. No automated replay/reconciliation protocol is introduced; operator or CLD-006 repair handles exhausted gaps. A 409 sequence gap is retryable/held, never terminal; only invalid auth/schema or irreconcilable fingerprint conflict is terminal.
- Impacted files/systems: Cloud `backend/activities/**`, `backend/config/api.py`, migrations/tests; Foundry `backend/runtime/services/events.py`, event publisher/outbox modules, API/schema additions, migrations/tests.
- Exit criteria: Duplicate exact event is a no-op, conflicting identity/sequence is rejected without mutation, stale attempt/generation and foreign Workspace/Ally/conversation are denied, safe terminal event requires FND-007 terminal/session evidence, and public read is capability-scoped.

### Phase 4 - Joint staging validation and rollout

- Goal: Prove compatibility and rollback behavior across independently deployable services.
- Work items: Run fixture parity in both repos; deploy Foundry endpoint first, then Cloud adapter/projection behind one disabled-by-default global flag; run sanitized staging command/event flow; verify metrics count accepted/duplicate/conflict/unknown/gap without payloads; document global enable/disable rollback. Future v2 compatibility is a separate rollout requirement.
- Impacted files/systems: CI workflows, deployment secret inventory, docs/contracts, staging runbook updates only (no Railway IaC commit).
- Exit criteria: Contract suite and sanitized staging evidence pass; rollback to adapter-disabled leaves accepted messages queued/reconciliation-needed without deletion; no public/log/metric/trace artifact contains credentials, raw payloads, private IDs, or URLs.

## Acceptance Criteria

1. The merged `bef7278` foundation is consumed as-is: UUID PK/FKs are used everywhere, no `public_id` layer is introduced, and CLD-005 adds no identity-reset, cutover, waitlist-preservation, or CLD-004 ancestry work.
2. One accepted CLD-004 `Message` produces at most one Foundry execution intent using `Message.id` and `Message.sequence`, including exact retry, concurrent race, timeout, and lost-response reconciliation; CLD-005 adds no parallel Cloud `ExecutionIntent` model.
3. Duplicate command/event with the same canonical fingerprint is a no-op/replay; conflicting identity/fingerprint/sequence is rejected without mutation.
4. Events cannot cross Workspace, Ally, conversation, execution, attempt, or generation boundaries; foreign-resource denial is privacy-safe.
5. Cloud projects `queued`, `running`, `awaiting_action`, `completed`, `stopped`, and `failed` truthfully; completion requires durable Foundry terminal event plus effective session update.
6. Each accepted message receives one immutable `conversation_turn_ordinal` at CLD-004 acceptance; every command/event carries and echoes it unchanged. Cloud orders valid events by `(conversation_turn_ordinal, generation, attempt_id, attempt_sequence, stable_event_id)`; stale generations are rejected/held before ordering, duplicates reuse product sequence, later turns wait for prior terminal evidence, and concurrent executions cannot collide.
7. Projection stores only bounded assistant text, safe activity summaries, terminal state, last contiguous sequence, and immutable receipts; CLD-006 owns cursor/replay/reconnect/stop/retry/repair.
8. Unknown versions/kinds, malformed fingerprints, oversized payloads, unsafe fields, timeout, unavailable, partial failure, and sequence gap fail closed with bounded retry/reconciliation; sequence gaps are held/retryable and never terminally discarded.
9. Contract tests run without a live Fly Machine; sanitized staging evidence proves deployed compatibility.
10. Cloud APIs, DTOs, routes, correlation fields, logs, metrics, traces, stored projections, and admin/operator evidence contain no command bytes, customer text, credentials, lease/profile/session keys, runtime addresses, raw provider/tool payloads, exceptions, or private Foundry authority.

## Backend Considerations (if applicable)

### Query Optimization Plan

- Hotspots/endpoints: conversation message creation, intent claim/reconciliation, event projection, activity feed.
- Query-shape choices: `select_related` for Workspace/Ally/conversation/intent; `select_for_update` on intent and feed rows; indexed `(status,next_attempt_at,lease_expires_at)`, `(conversation,product_sequence)`, and composite event identity; feed reads bounded to 200 rows.
- Expected query-count change: new write paths remain constant-query per message/event; no relation-heavy loops; publication task batches due rows up to 20.
- Measurement/monitoring plan: query-count assertions on service tests; sanitized duration/count metrics only; inspect PostgreSQL plans before staging enablement.

### N+1 Prevention

- Relation access map: message response loads conversation/Ally once; activity feed loads only public activity rows; projector locks intent/conversation in one transaction.
- Prefetch/select plan: `select_related("conversation__ally", "intent")`; no unbounded prefetch.
- N+1 regression guardrails: pytest query-count tests for message acceptance and activity reads; lint/review check that gateway calls never occur in per-row ORM loops.

### Detailed Unit Test Cases

- Happy path: accepted command, duplicate receipt, event sequence 1..N, assistant delta, activity start/complete, awaiting action, completed/stopped/failed terminal projection.
- Validation and bad input: unknown version/kind/field, bad digest, wrong NFC/fingerprint, oversized text/event/aggregate, NaN/Infinity, malformed IDs, unsupported state transition.
- Auth/RBAC boundaries: invalid service token, missing token, current Workspace membership, foreign Workspace/Ally/conversation/binding, stale generation/attempt, privacy-safe 404.
- Idempotency/retry behavior: concurrent same key, exact timeout retry with captured command-request-byte equality after restart, dispatch reconciliation accepted/not-found/conflict, duplicate event, event identity conflict, sequence conflict/gap, 60-second lease expiry, five-attempt command exhaustion, eight-delivery event-gap exhaustion, jitter bounds, operator receipt, and retention lookup; resolved outbox cleanup, conversation deletion, account deletion, and repeated cleanup are idempotent and leave no command bytes in admin/evidence surfaces.
- Failure-path behavior: Foundry 401/404/409/422/429/5xx, timeout, malformed response, event publication retry, Cloud DB rollback, partial outbox delivery, out-of-order N+1/N recovery, terminal monotonicity, and concurrent outbox workers racing on one event; multiple executions in one conversation, same-Ally retries/fresh attempts retaining one turn ordinal, later-turn-before-terminal holding, ordinal tampering, and concurrent different-Allies product-sequence allocation.

## Test Plan

- Unit tests: Cloud message-linked dispatch, `activities/tests`, gateway contract tests; Foundry execution/API/event publication tests. UUID-reset/waitlist-cutover tests are foundation evidence and are not rerun as CLD-005 acceptance.
- Integration/API tests: Django test client with fake service tokens and fake HTTP provider; cross-repository JSON fixture parity; no live Fly Machine required.
- Regression checks: Existing Cloud allies/provisioning/auth suites; existing Foundry FND-007 event/terminal/lease/concurrency suites.
- Manual verification checklist: inspect OpenAPI routes; run one staging message; confirm queued→running→assistant activity→completed; force timeout and verify reconciliation-needed; re-submit the exact event; inspect logs/metrics for absence of private data; verify unauthorized read returns same privacy-safe 404 as missing resource; verify bounded snapshot read returns last-contiguous sequence without cursor semantics.
- Commands (Cloud): `make sync`; `make check`; `make migrations APP=chat`; `make migrations APP=activities`; `make migrate`; `cd backend; uv run pytest chat/tests activities/tests allies/tests/test_foundry_gateway.py`; `make lint`; `make format` (check diff); `cd backend; uv run pytest --cov=chat --cov=activities --cov=allies`.
- Commands (Foundry): `make sync`; `make check`; `make validate`; `cd backend; uv run --locked pytest runtime/tests/test_cld005_contract.py runtime/tests/test_uuid_fixture_parity.py runtime/tests/test_fnd007_execution.py runtime/tests/test_services.py runtime/tests/test_api.py`; `make runtime-test`; `make lint`; `make format` (check diff). Multi-path tests run directly because `make test APP=...` accepts one pytest path argument.
- CI basis: Cloud `.github/workflows/ci.yml` (Django checks, migration checks, pytest, auth coverage, Ruff, PostgreSQL concurrency); Foundry `.github/workflows/ci.yml` and `scripts/validate.py` (backend/runtime locked tests, coverage XML, migration/config checks); staging HTTPS workflow remains health-only.

## Risks and Mitigations

- Risk: Cloud/Foundry schema drift during independent deploys. Mitigation: checked-in shared v1 JSON fixtures, strict `extra=forbid`, unknown-version rejection, Foundry-first rollout, contract CI in both repos; future v2 requires a separate compatibility artifact. Rollback/fallback: disable the one global Cloud dispatch/projection flag; leave accepted messages queued/reconciliation-needed; retain strict v1 parser and outbox.
- Risk: Ambiguous dispatch duplicates runtime work. Mitigation: intent-derived command key, canonical fingerprint, Foundry unique `(workspace,idempotency_key)`, reconciliation before retry, no auto-replay after dispatch evidence. Rollback/fallback: stop dispatch attempts and operator reconciliation; never create a new key.
- Risk: Event replay/order/stale-attempt corruption. Mitigation: immutable Cloud `conversation_turn_ordinal`, explicit generation/attempt identity, deterministic ordering `(conversation_turn_ordinal, generation, attempt_id, attempt_sequence, stable_event_id)`, stale-generation rejection, conversation lock, immutable receipts, and monotonic terminal transition. Gaps within a turn and later-turn-before-terminal are held as retryable; arrival time never establishes order. Rollback/fallback: retain the last truthful projection, retry event gaps for the eight-delivery event budget, then write `delivery_exhausted`/operator reconciliation state; operator/CLD-006 repair handles recovery without automated replay.
- Risk: Cloud command retry changes request bytes after restart or retains customer text after resolution. Mitigation: persist canonical UTF-8 command bytes, byte length, and SHA-256 in `DispatchOutbox`; transmit stored bytes directly and compare captured requests across retries; exclude bytes from admin/log/evidence surfaces and delete resolved rows with owning message/conversation/account deletion. Rollback/fallback: quarantine mismatched dispatch as reconciliation-needed, retain only until resolved, and never issue a rebuilt command.
- Risk: Runtime/provider data leakage. Mitigation: allowlisted DTOs, bounded safe payloads, private refs isolated to adapter/outbox, redaction tests, sanitized observability. Rollback/fallback: reject event/command and disable publication if sanitizer fails; do not redact unknown fields silently.
- Risk: Cross-repository rollout or credential failure. Mitigation: rotatable server secrets, timeout/body limits, fake-provider tests, staging endpoint evidence, deployment order Foundry→Cloud. Rollback/fallback: rotate/revoke credential, disable adapter, preserve durable Cloud intent and Foundry event outbox; retain exhausted operator receipts for the configured retention window and verify recovery by exact identity.
- Retry policy: Cloud dispatch lease is 60 seconds, maximum 5 attempts, backoff `min(300s, 2^(attempt-1))` with 0–25% jitter; Foundry event-delivery lease is 60 seconds, maximum 8 deliveries, the same capped backoff/jitter, and terminal `delivery_exhausted` only after the eighth failed delivery. `401/422` and irreconcilable fingerprint conflict are terminal immediately; `404` binding denial is privacy-safe terminal; `409 sequence_gap`, `408/429`, `5xx`, timeout, and network errors are held/retryable. Every exhausted record stores only identity, fingerprint, last sequence, safe error code, attempt count, and timestamps; operator reconciliation reuses the same identity and is covered by retention/recovery tests.
- Open decisions: none. The approved plan proceeds directly to implementation; route and existing command-secret names follow current repository conventions, while event delivery remains separately scoped as required by the accepted contract.
