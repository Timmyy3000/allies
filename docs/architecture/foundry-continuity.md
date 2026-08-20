---
title: Foundry continuity contract
status: working contract
audience: Allies Foundry and runtime contributors
---

# Foundry continuity contract

This document fixes the smallest contract needed to prove that an Ally survives
the loss of its Fly Machine. It describes who owns each piece of state, how the
runtime claims work, and what the proof must show. It does not define Django
models or implement a Fly or Hermes client.

## System path

```text
Allies Interface
    ↓ Allies Cloud
Allies Foundry control plane
    ↓ authenticated outbound claims
allies-runtime in a tenant Fly Machine
    ↓ localhost HTTP and SSE
Hermes profiles and sessions
    ↓
tenant Fly Volume at /opt/data
```

Cloud owns the user-facing conversation. Foundry owns durable execution truth.
Hermes runs the agent and keeps profile-local state. The Interface never talks
to Hermes or a Fly Machine directly.

## Durable mapping

```text
tenant → Fly app / Volume / active Machine / Machine generation
Ally → Foundry profile → Hermes profile key
Ally profile → one Cloud conversation ID + current Hermes session ID
execution → attempt → profile-scoped runtime lease
```

The Cloud conversation ID is fixed for each Ally in the initial product. Hermes
may rotate its session ID. The runtime reports the expected current ID and the
effective returned ID; Foundry updates the binding with compare-and-set
behavior.

## Concurrency contract

- Different Ally profiles in one tenant may stream concurrently.
- The proof uses at least two runtime worker slots.
- One Ally profile may hold only one active turn lease.
- A later turn for a busy profile remains queued.
- Claim selection and lease creation happen in one database transaction with an
  active-profile uniqueness constraint.
- Claim ordering beyond eligibility is unspecified in M1.

This is the intended meaning of "one active writer": one active Fly Machine may
write a tenant Volume. It does not mean one Ally execution per tenant.

## Runtime claim API

All endpoints live under `/api/v1/runtime/`. The runtime sends
`Authorization: Bearer <runtime token>`. The token identifies one workspace and
the current Machine generation.

| Operation | Request data | Success | Retry or rejection |
| --- | --- | --- | --- |
| `POST /claims` | Available worker slots | `200` with an attempt, lease token, expiry, command, and payload; `204` when idle | `409` fences the generation; `429`, `5xx`, and network errors use bounded backoff |
| `POST /attempts/{id}/lease/renew` | Opaque lease token | New expiry | `409` stops local work and prevents further mutations |
| `POST /attempts/{id}/events` | Lease token, attempt-local sequence, stable event ID, type, payload | `202`; duplicate event IDs are harmless | Retry only transport, `429`, and `5xx` with the same identifiers |
| `PUT /attempts/{id}/session-binding` | Lease token, expected current session ID, effective session ID | Idempotent compare-and-set update | `409` for conflicting conversation/session, token, or generation |
| `POST /attempts/{id}/stopped` | Lease token and stop reason | Confirms the Hermes stream ended | Required before same-profile reclaim unless the old Machine was fenced and stopped |
| `POST /attempts/{id}/complete` | Lease token, terminal event identity/sequence/payload, and receipt | Atomically appends `execution.completed` and completes the attempt | `409` for stale or conflicting writers |
| `POST /attempts/{id}/fail` | Lease token, terminal event identity/sequence/payload, typed failure, and receipt | Atomically appends `execution.failed` and fails the attempt | Same fencing and idempotency rules as completion |

Foundry derives profile, conversation, runtime, and generation scope from its
own attempt and lease records. Clients cannot replace that scope by repeating
IDs in a request body.

The first runtime claim loop uses immediate short polling. Idle backoff grows
exponentially from 1 to 10 seconds with bounded jitter, and a successful claim
or transport recovery resets it to 1 second. Long polling and WebSockets are
deferred until measured usage justifies them.

## Lease safety

Prototype leases last 60 seconds and renew every 20 seconds. If renewal fails,
the runtime cancels Hermes at least five seconds before expiry and sends
`stopped` when the stream ends.

Foundry does not immediately reclaim an expired attempt for the same Ally. It
waits for the matching `stopped` receipt, or retires the old Machine generation
and confirms that the old Machine stopped. This prevents two Hermes streams for
one Ally during a network partition.

The runtime confirms a durable `execution.dispatched` event before its first
Hermes session or stream request. Work stopped before that checkpoint may be
requeued. Once the checkpoint or a session receipt exists, stopped
acknowledgement and Machine fencing mark the execution failed and unknown-safe;
they never replay the message automatically.

Replacement retires the old generation as its first atomic transition. All old
claims, renewals, events, session updates, and terminal mutations fail from
that point onward.

## FND-004 runtime deployment proof

FND-004 adds the independently packaged `runtime/` process beside the pinned
Hermes image. The image entrypoint is baked into the runtime image and uses
`--serve`, so the runtime remains PID 1 instead of depending on a Fly command
override. It accepts only an opaque `HERMES_CREDENTIAL_REF`; a secure resolver
must be supplied by the live composition boundary. The process performs an
authenticated Hermes `/health/detailed` probe before it waits as PID 1, and
exits without reporting readiness when the reference, resolver, or probe is
missing.

The provider sends the same opaque reference under `HERMES_CREDENTIAL_REF` to
the `allies-runtime` container. It never sends a plaintext key. For normal
references, the image resolves that reference through a secure workload-local
Unix socket before performing its authenticated readiness probe; the default
socket is `/run/allies-runtime/hermes-credential.sock`. For the proof-only
`test://fnd004/…` scheme, PID 1 remains alive but unready during a bounded
bootstrap grace while the live bootstrap installs the temporary Hermes
profiles/keys. It becomes ready only after the authenticated probe succeeds.
The runtime does not write the Hermes Volume. The local proof uses a fake
Hermes client to show two different profiles overlap, a second turn for one
profile waits, and session/event identities remain isolated. The backend smoke
adapter reuses `FlyProvider` and `WorkspaceLifecycle`, records only its own
deterministic resource IDs, and cleans them through a bounded, idempotent
ledger.

The live proof is opt-in. `compose_live_smoke` fails closed unless Fly
multi-container capability, an immutable runtime image, an opaque reference,
an authenticated resolver, and the temporary profile bootstrap are supplied.
For proof-only runs, the explicit `test://fnd004/…` reference scheme derives a
non-secret fixture credential; other schemes use the workload-local socket.
The live bootstrap must still install the matching temporary profiles/keys
after the Machine starts and confirm authenticated readiness before the
lifecycle writes the durable Workspace binding. The smoke client runs its
health/stream checks only after that gate. Temporary profiles are proof
fixtures only; production profile seeding and secret delivery remain later
tickets.

Every lease/generation-authorized attempt mutation keeps its authorization and
write in the same database transaction. The exported runtime service accepts
only declarative status and claim-time fields; it performs those bounded writes
inside the transaction, so automatic retries contain database work only and do
not re-run arbitrary caller code. Event append uses the same lock-only
authorization seam inside its own transaction; that internal seam rejects
calls made outside an atomic caller.

Attempt status follows `queued → leased → running → succeeded | failed |
cancelled | unknown`; a queued attempt may move directly to `running` when the
claim path does not expose the intermediate lease state. Terminal statuses are
idempotent but immutable, so a stale writer cannot regress or replace a terminal
receipt. `claimed_at` is write-once: it may be set while an attempt is leased or
running, then cannot be cleared or changed. Ordinary attempt mutations and event
appends require an `active` lease. `stopping` is reserved for the FND-005
stop-acknowledgement path and cannot authorize normal runtime writes. New events
are accepted only for nonterminal attempts (`queued`, `leased`, or `running`);
an exact event replay remains idempotent after a terminal receipt. Lease state
choices are also enforced by a database check constraint.

## Hermes contract

Hermes is reachable only inside the Machine at
`http://127.0.0.1:8642`, using its `API_SERVER_PORT` setting.

The runtime uses:

```text
POST /p/{profile_key}/api/sessions/{session_id}/chat/stream
```

The profile key is immutable and must match
`[a-z0-9][a-z0-9_-]{0,63}`. Foundry-generated keys must also avoid Hermes'
reserved names: `hermes`, `default`, `test`, `tmp`, `root`, and `sudo`. The
runtime sends the profile-local bearer key, a stable
`X-Hermes-Session-Key`, and the known session ID when resuming. It records a
rotated session ID from the terminal `run.completed` event payload. The
streaming response header reports the requested path session ID and is not
enough to detect rotation.

A successful stream ends with `run.completed` followed by `done`. An explicit
error, malformed or out-of-order event, early disconnect, connection timeout,
or total-turn timeout fails the attempt with a typed reason. A fenced runtime
closes the stream and sends no further events.

The runtime recognizes only `run.started`, `message.started`,
`assistant.delta`, `tool.started`, `tool.completed`, `assistant.completed`,
`run.completed`, `error`, and `done`. It ignores the three non-durable
lifecycle signals and fails closed on every unknown event. Foundry stores only
`execution.dispatched`, `message.delta`, `activity.started`,
`activity.completed`, `execution.completed`, and `execution.failed`, with
bounded per-type payloads that exclude raw tool arguments, results, previews,
URLs, headers, exceptions, and credentials.

## Machine replacement

Foundry's Fly reconciler owns this sequence:

1. Atomically mark the workspace replacing and retire the old generation.
2. Stop the old Machine and wait for `stopped`.
3. Destroy it and wait for the Volume to detach.
4. Create the two-container replacement with the same Volume.
5. Start it, wait for health, activate the new generation, and allow claims.

The sequence is safe to retry after provider timeouts. A Volume attachment
conflict blocks execution rather than starting a second writer.

### Workspace lifecycle service

Foundry implements this sequence through the internal
`runtime.services.workspaces` service. Its only public service operations are
`ensure_workspace(workspace_id, spec)` and
`replace_machine(workspace_id, spec, expected_source_generation)`. A Workspace
row records the operation ID, phase, source/target generations, previous
Machine, deterministic target name, and a short claim token. The service locks
that row only while claiming a phase or recording a compare-and-set result;
Fly requests run after the transaction commits. Each claim lasts 60 seconds,
covering the longest bounded provider reconciliation sequence, and stale
callers lose at the compare-and-set boundary.

Ensure creates or reconciles the deterministic App and the single Volume,
checks `attached_machine_id` before creating a Machine, then waits for the
started Machine and both required, named container health checks before binding
all three provider references atomically. The adapter sends those checks in
the Machine config; FND-004 will replace the minimal process-liveness checks
with the Hermes/runtime readiness checks. A bound Workspace whose recorded
Machine is missing returns `replacement_required`; ensure never creates an
implicit second writer.

Replacement first advances the generation and clears `machine_ref` in one
short transaction. Only the recorded previous Machine may then be stopped and
destroyed, and the service waits for the Volume to detach before creating the
next deterministic Machine. Same-source retries replay the completed target;
stale source generations conflict. Retryable provider failures clear the claim
and retain the phase for bounded reconciliation (five attempts with
0.5/1/2/4-second jittered backoff), while terminal errors preserve a failed
phase for explicit repair. Unknown provider Machines are never deleted.

## Test doubles and proof matrix

The fake Hermes service must cover profile selection, new and resumed sessions,
authentication failure, session rotation, ordered events, explicit errors,
malformed SSE, disconnects, timeouts, cancellation, and duplicate event
delivery.

The fake Foundry and Fly boundaries must prove:

| Invariant | Test |
| --- | --- |
| One active turn per Ally | Parallel claims for one profile produce one lease |
| Different Allies run together | Two profiles fill two worker slots without crossed events or sessions |
| Renewal loss is safe | Hermes stops before expiry and reclaim waits for `stopped` or Machine retirement |
| One conversation per Ally | Conflicting conversation or session binding returns `409` |
| Lease ownership is strict | A token used against another attempt returns `409` |
| Replacement fences old work | Two live profiles and parameterized old-generation mutations fail in every replacement phase |

## Not in this ticket

FND-001 does not add Django domain apps, migrations, a Fly provider, the
runtime package, a Hermes client, Cloud changes, Interface changes, queues,
Redis, or Postgres. Those belong to later tickets after this contract is
reviewed and validated.
