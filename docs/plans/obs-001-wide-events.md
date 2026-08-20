# OBS-001 Wide Event Logging — Foundry

## Feature Overview

- Problem: Foundry API and runtime failures currently require stitching together ordinary process output. Alpha operators need one bounded, privacy-safe event shape that can be correlated with Cloud requests and later sent to SigNoz.
- Target users: Allies engineers and operators debugging Foundry API/runtime incidents.
- Source docs/specs: Allies OBS-001 planning spec; Docsyde wide-event pattern; `ENGINEERING_STYLE.md` (AL-05, AL-07–AL-12, FND-01, OSS-03–OSS-05).
- Success outcome: Foundry Django API and `runtime/allies_runtime` emit the same `WideEventV1` field names and safety rules as Cloud, using stdout as the primary sink and an optional fail-open sink seam.

## User Stories

1. As an operator, I want a failed Foundry API/runtime operation to expose operation, status, duration, outcome, and correlation IDs, so that I can locate the failure quickly.
2. As an operator, I want runtime retries, provider failures, and slow operations to be retained without logging tenant payloads, so that debugging remains safe for a public repository.
3. As a maintainer, I want the future SigNoz/OTLP adapter to be additive and optional, so that local contributors can run Foundry without private services or new infrastructure.

## Scope

### In Scope

- A Foundry-local implementation of the versioned `WideEventV1` contract, kept structurally compatible with Cloud but without importing Cloud code.
- Django API middleware for safe request ID generation/echo, route/status/duration/outcome/error fields.
- Runtime process event helpers around existing coordinator/worker/provider boundaries for started/succeeded/failed/retried operations; use existing execution/attempt/lease identifiers only when already available.
- Single-line JSON stdout formatter, allowlisted context, recursive redaction, and strict bounds.
- A narrow sink protocol/dispatcher with disabled-by-default, asynchronous, bounded, fail-open behavior; no OTLP/SigNoz dependency in this phase.
- Tests for public-safe fixtures, event parity, provider/worker failures, and no behavior or persistence changes.

### Out of Scope

- Request or runtime payload/body logging, prompts/messages, tool inputs/results, raw provider responses, SQL/query capture, or broad tenant/user enrichment.
- Full OpenTelemetry SDK, W3C trace/span propagation, collector deployment, SigNoz provisioning, dashboards, and alert configuration.
- Changes to runtime execution, lease, event ordering, provider contracts, database models, migrations, or public API response bodies.

### Dependencies and Assumptions

- Cloud remains the product-facing owner; Foundry continues to own runtime truth under FND-01.
- The parity contract is maintained through a small JSON fixture or equivalent schema assertion in both repositories, not a shared package or hidden import.
- Existing Foundry API and runtime tests remain the behavioral baseline; observability must not make provider/network paths mandatory.

### Cross-repository parity artifact

Both repositories carry the byte-identical fixture at `docs/contracts/observability/wide-event-v1.json`. It defines required names, JSON types, allowed event names, and redaction categories, with no secrets or private examples. A single root-level CI job/script owns parity checking (no repository-local duplicate scripts). The job checks out Cloud and Foundry at explicit paths supplied to it, then runs:

```text
python tools/compare_observability_contract.py --cloud-path "$CLOUD_CHECKOUT/docs/contracts/observability/wide-event-v1.json" --foundry-path "$FOUNDRY_CHECKOUT/docs/contracts/observability/wide-event-v1.json"
```

The root helper compares bytes and fails on mismatch. Each repository's local tests compare its implementation to its own fixture and accept an optional peer-fixture path supplied by CI; they do not invent a second parity script. A schema change updates both copies in one reviewed change.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `backend/observability/events.py` | `build_event` | `build_event(kind: str, **fields) -> dict[str, object]` | Allowlisted strings/numbers/booleans; sensitive keys redacted; values and serialized event bounded | JSON-serializable `WideEventV1` mapping | No DB/network I/O; never raises into runtime operation |
| `backend/observability/middleware.py` | `WideEventMiddleware.__call__` | Django middleware callable | Strict incoming ID validation; route/status/error metadata only | Original response plus additive `X-Request-ID` | Emits once in `finally`; logging failures swallowed |
| `runtime/allies_runtime/observability.py` | `emit_runtime_event` | `emit_runtime_event(event: Mapping[str, object]) -> None` | Event names limited to runtime lifecycle/provider outcomes; no payload fields | None | Writes stdout and optionally dispatches to sink; fail-open |
| `backend/observability/sinks.py` | `EventSink.offer` | `offer(envelope: bytes) -> OfferResult(accepted: bool, dropped: bool)` | Immutable UTF-8 serialized envelope, already bounded and schema-validated | Immediate non-blocking result | Adapter owns batching, timeout, retry, and lifecycle; offer performs no network I/O or recursive logging |

Runtime instrumentation is limited to named existing boundaries: `runtime/allies_runtime/coordinator.py:ProfileProofCoordinator.run_turn` (turn started/succeeded/failed and duration, using profile/session/run IDs only); `runtime/allies_runtime/foundry.py:FoundryWorker.run` and its per-turn execution path (worker started/idle/failed, preserving existing max-turn and idle behavior); `runtime/allies_runtime/hermes.py:HermesClient.stream_profile` (provider/Hermes call outcome and duration, no message or stream payload); and backend provider lifecycle service calls in `backend/runtime/services/workspaces.py` plus `backend/runtime/providers/fly.py` operations (operation name, provider error class, duration, opaque resource IDs only). Do not instrument every helper or persistence method.

Lifecycle matrix:

| Boundary | Started | Success | Failure/retry | Correlation | Hard-crash limit |
| --- | --- | --- | --- | --- | --- |
| `ProfileProofCoordinator.run_turn` | before client call | after accepted stream identity/replay filtering | exception class/error code, re-raise unchanged | profile/session/run IDs, sanitized | no terminal event if process dies |
| `FoundryWorker.run` | worker loop/process | loop exits normally | provider/runtime exception and retry count where existing | execution/attempt IDs when present | restart log/process health required |
| `HermesClient.stream_profile` | before provider request | stream completes | timeout/provider error | profile/session IDs | no completion on hard kill |
| workspace services / `FlyProvider` | each bounded provider operation | response mapped | provider timeout/conflict/retry outcome | workspace/operation/resource IDs as keyed digests | provider-side state remains source of truth |

### API and Transport Contracts

No public API body or Foundry runtime protocol is changed. `X-Request-ID` is an additive response header. Incoming IDs that are missing, invalid, or oversized are replaced with a server-generated ID; valid IDs are normalized before echoing. Do not introduce a trust relationship for arbitrary `traceparent` headers in this slice.

Representative API event:

```json
{"schema_version":1,"event":"http.request","occurred_at":"2026-08-20T12:00:00.000Z","service":"foundry","process":"web","environment":"staging","revision":"abc123","request_id":"...","correlation_id":"...","method":"POST","route":"/api/v1/runtime/executions","status_code":502,"duration_ms":410,"outcome":"error","error_type":"ProviderUnavailable","sampled":true}
```

Representative runtime event:

```json
{"schema_version":1,"event":"runtime.operation.failed","occurred_at":"2026-08-20T12:00:01.000Z","service":"foundry","process":"runtime","environment":"staging","revision":"abc123","correlation_id":"...","workspace_id":"opaque-id","execution_id":"opaque-id","operation":"provider_call","duration_ms":1200,"outcome":"error","error_type":"ProviderTimeout","sampled":true}
```

`workspace_id`, `execution_id`, and similar identifiers are included only when already present and safe; no additional lookups are performed. Unknown additive fields are ignored by consumers; incompatible changes require a new schema version.

Privacy and error-path rules: API route values are route templates, never raw paths or query strings. Request, correlation, execution, workspace, attempt, lease, and provider resource IDs are accepted only as UUIDs or a documented opaque identifier grammar, truncated to a fixed length and keyed-digested when tenant-linked; no email/name is logged. Exception fields are limited to stable class, allowlisted error code, and bounded sanitized message fingerprint. Middleware emits final status and `X-Request-ID` in `finally`; it re-raises the original exception and never converts an error into a success response. Runtime/provider instrumentation records no payload, prompt, tool result, secret, provider response, or lease token. Adversarial tests cover path/query injection, secret-bearing exception text, oversized IDs, and cross-tenant identifier handling.

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `WideEventV1` | `backend/observability/events.py`, mirrored in `runtime/allies_runtime/observability.py` | Common fields: `schema_version:int`, `event:str`, `occurred_at:str`, `service:str`, `process:str`, `environment:str`, optional `revision`, `request_id`, `correlation_id`, operation fields, `outcome`, `sampled` | Common contract fields required; runtime-specific IDs nullable | JSON-lines compatible, bounded bytes/collections, allowlisted keys, no sensitive payloads | No migration; fixture/schema parity test in both repos |
| `FoundryObservabilitySettings` | `backend/config/settings.py` and runtime config | Enable flag, success sample rate, slow threshold, max event bytes, sink enabled, max queue size | Safe defaults; sink off; positive limits/rates validated | Invalid public configuration fails clearly at startup; no private host/path defaults | Adapter batch size, retry, timeout, and lifecycle remain future SigNoz adapter contract knobs; environment variables documented for clean OSS checkout |

### Frontend Interaction Shapes (if applicable)

Not applicable; no frontend changes.

## Phases

### Phase 1 — Foundry contract and API logging

- Goal: Establish parity with Cloud at the Django boundary.
- Work items: Add observability package and formatter; wire middleware after proxy-header normalization; add settings/env example; add request ID response header; test 2xx/4xx/5xx/slow and sensitive metadata handling.
- Impacted files/systems: `backend/observability/`; `backend/config/middleware.py`; `backend/config/settings.py`; `backend/config/tests/`; new observability tests.
- Exit criteria: API emits valid bounded events and does not alter responses, auth, proxy handling, or ORM query count; `make check`, `make validate`, `make lint`, and targeted tests pass.

### Phase 2 — Runtime lifecycle events and optional sink seam

- Goal: Make provider/worker failures diagnosable and prepare for later SigNoz sync.
- Work items: Add runtime helper at the narrow coordinator/worker/provider boundaries; emit lifecycle outcomes and durations using existing IDs; add a minimal bounded `put_nowait` fail-open sink dispatcher and disabled no-op sink with dropped counter; add parity fixtures and failure tests; document future OTLP adapter contract and staging proof. Batch size, retry, timeout, and lifecycle controls remain adapter-owned future knobs.
- Impacted files/systems: `runtime/allies_runtime/observability.py` and focused call sites/tests; `runtime/pyproject.toml` only if an existing dependency is genuinely needed; backend sink/config files; docs.
- Exit criteria: Runtime/provider exceptions still propagate or map exactly as before; emitted events contain no payloads/secrets; sink timeout/full queue cannot affect operation; runtime coverage and repository validation pass.

## Acceptance Criteria

1. Foundry web and runtime produce `WideEventV1` JSON-lines events with matching required names/types and `schema_version=1`.
2. API errors, provider failures, retries, and operations over the slow threshold are retained; routine successes are sampled according to a validated rate.
3. Events are bounded and redact credentials, authorization/cookie headers, private URLs/query strings, emails/names, prompts/messages, tool args/results, database URLs, and sensitive exception text.
4. Valid or generated request IDs are echoed as `X-Request-ID`; untrusted oversized IDs cannot become log fields.
5. Observability is side-effect free: no new database queries, migrations, provider calls, state transitions, or changed API/runtime error semantics.
6. The optional sink is disabled by default, asynchronous/bounded, and fail-open under timeout, queue-full, malformed-event, or adapter-error conditions. The seam offers only immutable serialized bytes and an immediate accepted/dropped result; adapter-owned batching, timeout, retry, shutdown, and non-recursive diagnostics never run in the API/runtime call path.
7. Public setup remains portable: no private URLs, credentials, or maintainer paths are required; environment knobs and rollback are documented.

## Backend Considerations (if applicable)

### Query Optimization Plan

- Hotspots/endpoints: Existing runtime API and health endpoints; event code must not access models.
- Query-shape choices: None.
- Expected query-count change: Zero.
- Measurement/monitoring plan: Assert query counts for representative API tests and ensure runtime event creation is pure.

### N+1 Prevention

- Relation access map: No relation/model reads for logging.
- Prefetch/select plan per endpoint/service: Not applicable.
- N+1 regression guardrails: Tests fail if observability causes ORM access.

### Detailed Unit Test Cases

- Happy path: request, runtime operation, provider success/failure, retry, and cancellation events serialize.
- Validation and bad input: invalid request IDs, non-JSON exception values, nested secrets, oversized collections/events.
- Auth/RBAC boundaries: anonymous and rejected API requests produce safe metadata only.
- Idempotency/retry behavior: retries are distinct lifecycle events with stable operation/execution IDs and monotonic retry count; no duplicate persistence writes.
- Failure-path behavior: event formatter, stdout handler, sink timeout, queue full, and adapter exception cannot mask original runtime/API failure.
- Sink contract: a fake adapter receives immutable bytes only, returns immediately with accepted/dropped, and verifies adapter batching/timeout/retry hooks outside the API/runtime call path; adapter errors cannot recurse through the observability logger.

## Frontend Considerations (if applicable)

Not applicable.

## Test Plan

- Unit tests: `WideEventV1` contract, sanitizer, bounds, sampling, request ID, middleware finalization, runtime helper, sink isolation.
- Integration/API tests: Django test client for status/error/slow behavior; runtime tests around coordinator/worker/provider failure and retry paths; parity fixture loaded by both repos.
- Regression checks: existing API response/body/status and runtime state/ordering remain unchanged; no extra DB/provider calls.
- Manual verification checklist: run Foundry web and runtime locally; force one API 500, one provider timeout/failure, one retry/slow operation; parse stdout; inspect prohibited fields; verify staging logs and correlation across a Cloud→Foundry request when available.
- Commands: `make check`; `make validate`; `make lint`; `make test APP=backend/config/tests backend/observability/tests`; `make runtime-test`; `cd runtime && uv run --locked ruff format --check .` as applicable.

Sampling semantics and counters: `sampled=true` means emitted/selected, not an estimate. Errors, retries, and slow operations are always emitted; routine successes may be sampled out. Emit bounded `events_emitted`, `events_sampled_out`, and `events_dropped` counters. Alert rates use emitted error events over the corresponding emitted operation population and never infer total traffic from sampled successes.

Rollout and fallback: ship stdout-only with the optional sink disabled; stage API 500, provider timeout, and runtime retry/failure examples; compare both contract fixtures in CI before enabling any adapter. Roll back by disabling the sink, then the event flag if volume or formatter risk appears. Existing process stdout and restart/health logs remain the fallback; hard process crashes can lose terminal events.

## Risks and Mitigations

- Risk: Runtime exceptions contain tenant/provider payloads. Mitigation: allowlist operation/error class and bounded sanitized message fingerprint; never emit raw payloads or provider responses. Rollback: disable events with env flag.
- Risk: A sink or queue blocks the runtime. Mitigation: bounded `put_nowait` queue, immediate drop result, drop counter, sink errors isolated from application logger; adapter-owned timeout/retry is deferred and never runs on the runtime call path; default sink disabled.
- Risk: Public repository accidentally documents internal infrastructure. Mitigation: generic env names and examples only; OSS checks for credentials/private paths/URLs.
- Risk: Cloud and Foundry drift in event shape. Mitigation: committed parity fixture and schema-version review gate; additive changes only for v1.
- Risk: Instrumentation changes lifecycle timing or event ordering. Mitigation: emit outside state transactions, preserve existing exceptions/ordering, and test state/event invariants.

## Accepted simplicity boundary and unresolved SigNoz questions

The alpha exposes exactly six knobs: `ALLIES_WIDE_EVENTS_ENABLED`, `ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE`, `ALLIES_WIDE_EVENTS_SLOW_MS`, `ALLIES_WIDE_EVENTS_MAX_BYTES`, `ALLIES_WIDE_EVENTS_SINK_ENABLED`, and `ALLIES_WIDE_EVENTS_MAX_QUEUE_SIZE`. Batching, retry, timeout, shutdown/lifecycle tuning, collector deployment, dashboards, and OTLP dependencies are deferred to the future SigNoz adapter; Foundry does not gain Celery or an OTLP dependency in this slice.

Open decisions for the future adapter (not implementation blockers here): which SigNoz ingestion protocol and authentication boundary to use; whether adapter-owned batching/retry/timeout defaults need service-specific values; what retention and drop-rate SLOs apply; and who owns dashboards/alerts. The current plan remains stdout-first and sink-disabled by default.
