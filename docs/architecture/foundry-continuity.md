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
Allies Foundry on Railway
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
| `POST /attempts/{id}/complete` | Lease token and terminal receipt | Idempotent completion | `409` for stale writers |
| `POST /attempts/{id}/fail` | Lease token, typed failure, retryability | Idempotent failure | Same fencing rules as completion |

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

Replacement retires the old generation as its first atomic transition. All old
claims, renewals, events, session updates, and terminal mutations fail from
that point onward.

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

## Machine replacement

Foundry's Fly reconciler owns this sequence:

1. Atomically mark the workspace replacing and retire the old generation.
2. Stop the old Machine and wait for `stopped`.
3. Destroy it and wait for the Volume to detach.
4. Create the two-container replacement with the same Volume.
5. Start it, wait for health, activate the new generation, and allow claims.

The sequence is safe to retry after provider timeouts. A Volume attachment
conflict blocks execution rather than starting a second writer.

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
