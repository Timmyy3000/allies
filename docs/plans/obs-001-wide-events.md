# OBS-001 Wide Event Logging — Cloud

## Feature Overview

- Problem: Alpha operators need one privacy-safe record that explains failed or slow Cloud API requests and Celery tasks, with enough correlation to debug cross-service failures.
- Target users: Allies engineers and operators debugging alpha/beta incidents.
- Source docs/specs: Nabu `projects/allies/planning/obs-001-observability-foundation.md`; Docsyde `core/logging/wide_events.py` and request/task logging pattern; `ENGINEERING_STYLE.md` (AL-05, AL-07–AL-10, CLOUD-02).
- Success outcome: Cloud web, worker, and beat processes emit bounded single-line JSON events to stdout, with stable correlation and an optional fail-open sink boundary suitable for a later SigNoz/OTLP adapter.

## User Stories

1. As an operator, I want every failed API request to produce a searchable structured event, so that I can identify route, status, error class, and correlation ID without reproducing the request.
2. As an operator, I want slow requests and failed/retried Celery tasks to be retained while routine successes can be sampled, so that logs remain useful and bounded.
3. As an operator, I want a disabled or failing SigNoz sink not to affect application work, so that observability cannot become an outage.

## Scope

### In Scope

- A versioned, shared event contract implemented in Cloud and mirrored by Foundry.
- Django middleware for request ID generation/validation, response `X-Request-ID`, duration, status, route template, outcome, and safe exception fields.
- Celery task lifecycle events for started, succeeded, failed, and retried tasks, including task ID and request correlation when available.
- One-line JSON stdout logging through the existing Python logging stack.
- Allowlisted fields, recursive redaction, bounded string/list/map sizes, and no request/response bodies, SQL, prompts, tool payloads, credentials, cookies, authorization headers, or raw query strings.
- Narrow sink protocol/dispatcher with asynchronous bounded delivery, disabled by default; no OTLP dependency is required in this phase.
- Configuration for service/process/environment/revision, success sampling, slow threshold, sink enablement, and maximum queue size.
- Focused unit/integration tests and staging manual proof; no schema migration.

### Out of Scope

- Implementing SigNoz, OTLP exporters, a collector, dashboards, or alert provisioning.
- Full W3C trace/span instrumentation or propagating trace context through every provider boundary.
- Request/response body capture, database query capture, broad user/workspace enrichment, or business analytics.
- Changes to public API response bodies or Cloud/Foundry domain contracts.

### Dependencies and Assumptions

- Railway captures stdout for Backend, Worker, and Beat; stdout remains the canonical sink.
- Foundry adopts the same event field names and privacy rules in its Django API and runtime process; cross-repo parity is verified with fixtures rather than shared Python imports.
- A later SigNoz adapter consumes the event object/protocol without changing middleware or task call sites.

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
| `backend/observability/events.py` | `WideEvent` / `build_event` | `build_event(kind: str, **fields) -> dict[str, object]` | Allowlisted scalar fields; sanitize recursively; cap event bytes and collection sizes | JSON-serializable event with `schema_version=1` | No I/O; invalid values become bounded type-safe representations |
| `backend/observability/sinks.py` | `EventSink` / `offer` | `offer(envelope: bytes) -> OfferResult(accepted: bool, dropped: bool)` | Immutable UTF-8 serialized envelope, already bounded and schema-validated | Immediate non-blocking result | Adapter owns batching, timeout, retry, and lifecycle; offer performs no network I/O or recursive logging |
| `backend/observability/middleware.py` | `WideEventMiddleware.__call__` | Django middleware request/response callable | Generate UUID request ID unless incoming ID matches strict safe format; never trust arbitrary headers as identity | Original response, with `X-Request-ID` | Emits exactly one request event in `finally`; logging failure cannot change response |
| `backend/observability/celery.py` | worker-only task signal handlers | Celery `task_prerun`, `task_postrun`, `task_failure`, `task_retry` in Worker/Beat processes only | Task name/id, retry count, monotonic start time, correlation context; sanitize exception metadata | None | Dedupe by `(task_id, lifecycle, retry_count)` in a bounded process-local cache; duration is `task_prerun` to terminal signal. A hard process crash may lose the terminal event. |

### API and Transport Contracts

No public HTTP or queue schema changes. The response header is additive:

```http
X-Request-ID: 01J...
```

Accepted incoming `X-Request-ID` is normalized to the safe token/UUID format and echoed; invalid or oversized values are replaced with a server-generated ID. No trace header is introduced in this phase.

Canonical event example:

```json
{"schema_version":1,"event":"http.request","occurred_at":"2026-08-20T12:00:00.000Z","service":"cloud","process":"web","environment":"staging","revision":"abc123","request_id":"...","correlation_id":"...","method":"POST","route":"/api/v1/auths/login","status_code":500,"duration_ms":842,"outcome":"error","error_type":"ProviderTimeout","sampled":true}
```

Task events use `event=task.started|task.succeeded|task.failed|task.retried`, `task_name`, `task_id`, `queue`, `duration_ms`, `retry_count`, and the same service/process/environment/revision/correlation fields. Events are additive, stdout-only, and consumers must ignore unknown fields; `schema_version` changes only for incompatible shape changes.

Privacy and error-path rules: route values are Django route templates only, never raw paths or query strings. Request, correlation, task, and tenant-linked IDs are accepted only as UUIDs or a documented opaque identifier grammar, truncated to a fixed length and emitted as a keyed digest where the identifier could identify a tenant; no email/name is used as an ID. Exception fields are limited to stable exception class, a short allowlisted error code, and a bounded sanitized message fingerprint. Middleware emits the final status code and `X-Request-ID` in `finally`; if application code raises, it re-raises unchanged and does not replace the response or add a misleading success event. Adversarial tests cover secret-bearing exception text, path/query injection, oversized IDs, and tenant-linked identifiers.

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `WideEventV1` | `backend/observability/events.py` | `schema_version:int`, `event:str`, `occurred_at:str`, `service:str`, `process:str`, `environment:str`, `revision:str?`, `request_id:str?`, `correlation_id:str?`, operation fields, `outcome:str`, `sampled:bool` | Contract fields required; operation/context fields nullable | JSON-serializable, bounded to a configured byte limit, sensitive keys/values redacted | No database migration; additive fields allowed within v1 |
| `ObservabilitySettings` | `backend/config/settings.py` | `ALLIES_WIDE_EVENTS_ENABLED`, `ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE`, `ALLIES_WIDE_EVENTS_SLOW_MS`, `ALLIES_WIDE_EVENTS_MAX_BYTES`, `ALLIES_WIDE_EVENTS_SINK_ENABLED`, `ALLIES_WIDE_EVENTS_MAX_QUEUE_SIZE` | Enabled by default for stdout; sink disabled by default; positive bounds validated | Production config cannot set invalid rates, zero/negative limits, or unbounded queue | Environment-only configuration; adapter batch size, retry, timeout, and lifecycle remain future adapter-owned contract knobs |

### Frontend Interaction Shapes (if applicable)

Not applicable; no frontend changes.

## Phases

### Phase 1 — Cloud event core

- Goal: Emit safe, correlated request and task events without changing product behavior.
- Work items: Add observability package; configure JSON formatter/logger; add middleware after proxy normalization and before application middleware; register Celery signal handlers; add settings/env examples; implement sampling (retain all errors and slow events; sample routine successes).
- Impacted files/systems: `backend/observability/`; `backend/config/middleware.py`; `backend/config/settings.py`; `backend/config/celery.py`; tests under `backend/config/tests/` and `backend/observability/tests/`.
- Exit criteria: API and task events parse as one-line JSON; response ID is echoed; redaction/size limits and fail-open behavior are tested; `make check`, `make lint`, and targeted `make test APP=...` pass.

### Phase 2 — Optional sink seam and staging proof

- Goal: Make future SigNoz/OTLP delivery a configuration-only adapter addition.
- Work items: Define sink protocol and a minimal bounded `put_nowait` dispatcher; provide a disabled no-op sink and a dropped-event counter; document only the six alpha env knobs and leave batching, retry, timeout, and lifecycle to the future SigNoz adapter contract; run staging failure/slow/task examples and verify stdout records.
- Impacted files/systems: `backend/observability/sinks.py`, configuration/docs, staging Cloud services.
- Exit criteria: Sink disabled by default; artificial sink timeout/failure leaves request/task outcome unchanged; queue and event bytes are bounded; staging evidence captures request ID, task ID, duration, outcome, and revision without sensitive values.

## Acceptance Criteria

1. Every Cloud API request emits at most one `http.request` event with status, duration, route template, outcome, service/process/environment, and request ID; 5xx/4xx and requests over the slow threshold are never dropped by sampling.
2. Cloud Celery started/succeeded/failed/retried events include task name/id, queue, duration or retry count, outcome, and correlation when available; routine starts and terminal successes share a task-ID sampling bucket. Because duration is unknown at `task_prerun`, slow-task retention is evaluated on the terminal event, so a slow task may intentionally have terminal-only retained evidence.
3. Events are valid single-line JSON, bounded, and pass explicit redaction tests for headers, cookies, tokens, email, names, prompts/messages, tool arguments/results, URLs/query strings, database URLs, and exception text containing secrets.
4. `X-Request-ID` is server-generated or safely normalized and echoed on success and error responses; arbitrary untrusted IDs are not used as unbounded log keys.
5. Sink delivery is asynchronous/bounded and fail-open: the seam passes an immutable serialized envelope to a nonblocking `offer` and returns an accepted/dropped result. Disabled or failing sink cannot delay, fail, or alter an HTTP response or Celery task result; the future adapter owns batching, timeout, retry, shutdown, and non-recursive diagnostics.
6. Cloud and Foundry fixtures agree on `WideEventV1` required names/types and schema version; no database migration or public response-body change is introduced.

## Backend Considerations (if applicable)

### Query Optimization Plan

- Hotspots/endpoints: None intentionally added. Middleware must not query the database or inspect response bodies.
- Query-shape choices: None.
- Expected query-count change: Zero.
- Measurement/monitoring plan: Test request query count remains unchanged for representative endpoints.

### N+1 Prevention

- Relation access map: No model access from event construction.
- Prefetch/select plan per endpoint/service: Not applicable.
- N+1 regression guardrails: A test asserts event construction does not touch the ORM.

### Detailed Unit Test Cases

- Happy path: request event and each task lifecycle event serialize and include required fields.
- Validation and bad input: invalid/oversized request ID, unserializable exception/context, nested sensitive keys, and oversized collections are normalized/redacted/bounded.
- Auth/RBAC boundaries: logging works for anonymous, authenticated, and permission-denied responses without logging identity secrets.
- Idempotency/retry behavior: one request event per request; retries emit distinct task events with stable task ID and incremented retry count.
- Failure-path behavior: view exception, formatter failure, sink timeout, queue full, and sink disabled do not alter application outcome.
- Sink contract: a fake adapter receives only immutable bytes, returns immediately with accepted/dropped, never sees mutable event mappings, and its timeout/retry/batching hooks are exercised outside the request/task call path; adapter errors cannot recurse through the sink logger.

## Frontend Considerations (if applicable)

Not applicable.

## Test Plan

- Unit tests: event contract, sanitization, sampling, request ID handling, middleware finalization, task signals, sink fail-open/queue bounds.
- Integration/API tests: Django test client for 2xx/4xx/5xx/slow responses and header echo; Celery signal test with eager task or mocked signals.
- Regression checks: no response-body changes; no ORM query increase; existing logging remains readable for local development.
- Manual verification checklist: run Cloud web/worker/beat locally; force one 500, one slow endpoint, one task retry/failure; parse stdout with a JSON-lines parser; inspect that no prohibited fields occur; verify Railway staging logs.
- Commands: `make check`; `make lint`; `make test APP=backend/config/tests backend/observability/tests`; `make format --check` equivalent via `uv run ruff format --check .` if supported; staging smoke commands documented in the PR.

Sampling semantics and counters: `sampled=true` means the event was selected for emission, not that it is an estimate. Errors, retries, and slow events are emitted regardless of success sample rate. Emit bounded counters for `events_emitted`, `events_sampled_out`, and `events_dropped`; alert rates use emitted error events divided by the corresponding emitted request/task population and do not infer total traffic from sampled successes.

Rollout and fallback: deploy stdout events with the optional sink disabled; verify staging using a 500, a slow request, and a failed/retried task before production. Enable a sink only after fake-adapter contract and timeout tests pass. Roll back by disabling the sink first, then wide events if formatter/volume is unsafe; existing application logs and Railway stdout remain the fallback. A hard worker/process crash may leave no terminal task event, so process health and restart logs remain separate signals.

## Risks and Mitigations

- Risk: Sensitive data leaks through exception messages or arbitrary context. Mitigation: allowlist fields, recursive redaction, bounded serialization, prohibited-field tests; never log bodies or raw URLs. Rollback: disable wide events via env flag while retaining existing logs.
- Risk: Logging increases request/task latency or memory. Mitigation: no ORM/body work, bounded queue and event size, asynchronous sink, sampled successes, timing tests. Rollback: disable sink and reduce sampling/rate.
- Risk: Sink outage creates recursive logging or backpressure. Mitigation: sink errors are isolated, rate-limited, and never sent through the same sink; bounded drop counter. Rollback: set sink disabled.
- Risk: Cloud/Foundry event drift blocks future cross-service queries. Mitigation: versioned fixture contract and cross-repo staging proof; changes require additive v1 or explicit version bump.

## Cloud callsite and lifecycle matrix

Named Cloud callsites are intentionally narrow: `backend/config/middleware.py:TrustedProxyHeadersMiddleware` remains the proxy-normalization boundary and `backend/observability/middleware.py:WideEventMiddleware` runs immediately after it; `backend/config/celery.py:app` is the registration point for worker/beat-only Celery signals; and task modules under `backend/*/tasks.py` remain unchanged. No signal handlers are installed in the web process, and no Foundry Celery integration is added.

| Boundary | Started | Success | Failure/retry | Correlation | Hard-crash limit |
| --- | --- | --- | --- | --- | --- |
| Django request middleware | before view dispatch | final response in `finally` | exception class/code, re-raise unchanged | validated request/correlation IDs | no terminal record if process dies before `finally` |
| Celery worker task | `task_prerun` | `task_postrun` | `task_failure` / `task_retry`, retry count | task ID and propagated request context when available | terminal event can be lost on hard process crash |
| Celery beat task dispatch | beat-side signal only when emitted by the beat process | dispatch outcome | dispatch failure/retry | task ID/correlation when available | restart/health logs remain separate |

Signal ownership is worker/beat-only; dedupe key is `(task_id, lifecycle, retry_count)` in a bounded process-local cache. Duration is measured from prerun to terminal signal. Retries are distinct events, and a hard crash is explicitly not claimed to be observable. Task sampling is lifecycle-consistent for routine starts and terminal successes; the slow-task exception is deliberate because only the terminal signal knows whether the threshold was crossed, and the terminal event is retained even when its start was sampled out.

Retention contract: errors and retries use bounded burst retention that keeps one representative event after suppression, with bounded operator-visible suppression diagnostics. This terminal-only slow-task behavior is an accepted contract, not an unresolved lifecycle gap.

## Accepted simplicity boundary and unresolved SigNoz questions

The alpha exposes exactly six knobs: `ALLIES_WIDE_EVENTS_ENABLED`, `ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE`, `ALLIES_WIDE_EVENTS_SLOW_MS`, `ALLIES_WIDE_EVENTS_MAX_BYTES`, `ALLIES_WIDE_EVENTS_SINK_ENABLED`, and `ALLIES_WIDE_EVENTS_MAX_QUEUE_SIZE`. Batching, retry, timeout, shutdown/lifecycle tuning, collector deployment, dashboards, and OTLP dependencies are deferred to the future SigNoz adapter; Foundry does not gain Celery or an OTLP dependency in this slice.

Open decisions for the future adapter (not implementation blockers here): which SigNoz ingestion protocol and authentication boundary to use; whether adapter-owned batching/retry/timeout defaults need service-specific values; what retention and drop-rate SLOs apply; and who owns dashboards/alerts. The current plan remains stdout-first and sink-disabled by default.
