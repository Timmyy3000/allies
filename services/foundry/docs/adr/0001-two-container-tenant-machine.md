---
title: ADR-001: Two-container tenant Machine
status: accepted
date: 2026-08-05
---

# ADR-001: Two-container tenant Machine

## Decision

Each tenant runs its continuity proof in one Fly Machine with two containers:

1. `hermes`, built from the pinned Hermes image;
2. `allies-runtime`, built and released separately by Allies.

The containers share the Machine network namespace. `allies-runtime` calls the
Hermes API at `127.0.0.1`; Hermes is not public. The Hermes image's dispatcher
executes `/init` when it owns PID 1, while the runtime has its own process tree.
Whether Fly gives the Hermes container that PID-1 path is a required live proof
in FND-004, not an assumption this ADR treats as already proven.

The tenant Volume mounts at `/opt/data` in the Hermes container. Any runtime
mount used for idempotent profile seeding must be scoped and must not become a
second durable store. Only one active Machine may mount and write the Volume.

Foundry owns the tenant workspace, Machine lifecycle, claims, leases, events,
and generation fencing. The runtime calls Foundry over authenticated outbound
HTTPS. Foundry does not open an inbound port on the tenant Machine.

## Image provenance

The continuity proof uses the Hermes source inspected at commit
`36cb5ae5530a75def7df3195e49b7a4aa2add482` and the immutable image digest
`sha256:b6f18532e2c082ef6686c659fc222427e41fde3eed08aa058411f0ea5ab705ca`.
The digest was inspected from upstream workflow run `30953051642`. Any image
change must record a new source commit, digest, and inspection result here
before the proof is rerun.

## Context

Hermes uses s6-overlay and expects `/init` to be PID 1. The pinned image's
entrypoint dispatcher falls back to a foreground wrapper when a platform wraps
it under another PID-1 process. A normal Fly single-container process cannot
also use that process tree for an Allies sidecar. Fly's multi-container Machine
model gives each container its own process tree while keeping them on the same
localhost network, but FND-004 must still prove which Hermes process owns PID 1.

The Volume is durable tenant state. The Machine is replaceable compute. The
design must keep several Ally profiles active at once without allowing two
turns for one Ally to write the same conversation concurrently.

## Boundaries

| Component | Owns | Talks to |
| --- | --- | --- |
| Foundry control plane | Workspaces, profiles, executions, attempts, leases, ordered events, Machine records, and generation state | Cloud through a versioned API; runtime through outbound HTTPS; Fly through its provider adapter |
| `allies-runtime` | Local workers, Hermes calls, event forwarding, lease renewal, and stop acknowledgement | Foundry over HTTPS; Hermes over localhost |
| Hermes | Profile configuration, sessions, transcripts, skills, memories, and tool execution state | Runtime over its localhost API; the tenant Volume for durable files |
| Fly | Machine and Volume resources | Foundry's provider adapter |

Cloud owns customer-facing users, tenants, Allies, conversations, messages,
permissions, and product delivery. Cloud never connects directly to Hermes or a
Fly Machine.

## Runtime behavior

- Each Ally maps to one Foundry profile and one Hermes profile.
- Each Ally has one continuous Cloud conversation and one current Hermes session
  in the initial product.
- Different Ally profiles may run concurrently on the same Machine.
- A profile may hold only one active turn lease. A later turn for that profile
  waits.
- The runtime has a bounded worker pool. The continuity proof configures at
  least two slots.
- Claim selection and lease creation are one transaction protected by an
  active-profile uniqueness constraint.
- A lease token is bound server-side to one attempt, profile, conversation,
  runtime, and Machine generation. Request bodies do not get to redefine that
  scope.
- A Hermes profile key is immutable, matches
  `[a-z0-9][a-z0-9_-]{0,63}`, and is not one of the reserved names `hermes`,
  `default`, `test`, `tmp`, `root`, or `sudo`.
- The runtime reads an effective rotated session ID from the terminal
  `run.completed` event payload. The streaming response header is the requested
  path session ID and is not sufficient evidence of rotation.
- The first claim loop uses immediate short polling. When no work is available,
  idle backoff grows exponentially from 1 to 10 seconds with bounded jitter;
  any claim or transport recovery resets the delay to 1 second. Long polling and
  WebSockets are deferred until measured usage justifies them.

## Machine lifecycle

Foundry is the only component allowed to create, start, stop, update, or destroy
a tenant Machine.

Replacement begins by atomically retiring the old generation and rejecting all
claims and attempt mutations from it. Foundry then stops the old Machine, waits
for it to stop, destroys it, waits for the Volume to detach, creates the
two-container replacement with the same Volume, starts it, checks health, and
activates the new generation.

An old generation can never append events, rotate a session binding, or complete
an attempt after replacement begins.

## Environment ownership

Values below name the contract only. Secret values belong in the deployment
secret store and never in source, logs, or tenant working files.

| Process | Variable | Secret | Purpose |
| --- | --- | --- | --- |
| Foundry | `FOUNDRY_DATABASE_URL` | Yes | Foundry Postgres connection |
| Foundry | `FOUNDRY_ENCRYPTION_KEY` | Yes | Encryption for control-plane secrets |
| Foundry | `FLY_API_TOKEN` | Yes | Fly provider authentication |
| Foundry | `FLY_ORG` | No | Fly organization |
| Foundry | `FLY_REGION` | No | Default tenant Machine region |
| Runtime | `ALLIES_FOUNDRY_BASE_URL` | No | Foundry API origin |
| Runtime | `ALLIES_RUNTIME_TOKEN` | Yes | Runtime identity and workspace scope |
| Runtime | `ALLIES_RUNTIME_MAX_IN_FLIGHT` | No | Worker bound; at least `2` in the proof |
| Runtime | `ALLIES_MACHINE_GENERATION` | No | Machine generation presented by the runtime process |
| Hermes | `HERMES_HOME` | No | Durable state root, `/opt/data` |
| Hermes | `API_SERVER_HOST` | No | Bind address, `127.0.0.1` |
| Hermes | `API_SERVER_PORT` | No | Local API port, `8642` |
| Profile-local Hermes state | `API_SERVER_KEY` | Yes | Per-profile API authentication, stored only inside tenant state |

The runtime does not receive Cloud credentials or plaintext Hermes keys from
Foundry. Profile-local Hermes keys are generated and stored during idempotent
profile seeding.

The pinned image was verified on 2026-08-05 with:

```text
docker buildx imagetools inspect nousresearch/hermes-agent@sha256:b6f18532e2c082ef6686c659fc222427e41fde3eed08aa058411f0ea5ab705ca
```

The inspection must continue to resolve the recorded OCI index and its Linux
`amd64` and `arm64` platform manifests. The source SHA and successful upstream
workflow run above are the traceability record for that digest.

## Proof gate

FND-004 must prove all of the following before profile provisioning depends on
the topology:

- The actual Fly process tree proves whether the pinned image can run `/init` as
  PID 1 in its Hermes container. If Fly's wrapper prevents that path, FND-004
  must revise the container command or topology before profile provisioning.
- The runtime executable is PID 1 in its container.
- The runtime reaches the authenticated Hermes health/API endpoint on
  `127.0.0.1`.
- The intended `/opt/data` visibility is correct.
- Ally A and Ally B can stream at the same time without crossed profiles,
  sessions, or events.
- A second turn for one active Ally waits.

## Alternatives considered

### One derived image with shared s6

Rejected. It cannot preserve Hermes `/init` as PID 1 under Fly's normal process
model while also supervising the runtime.

### One Machine per Ally

Deferred. It would make profile concurrency easy but would multiply Machine and
Volume cost and would not test the durable tenant runtime boundary we need to
prove first.

### Public Hermes service

Rejected. Hermes credentials and session APIs stay inside the Machine. The
runtime is the only local caller.

## Consequences

This design keeps Hermes close to its supported container model and makes the
runtime independently deployable. It also means FND-004 must verify Fly's
multi-container Volume behavior before FND-006 relies on it. The Machine shares
resources among a tenant's Allies, so capacity must remain bounded. Profile
separation is state isolation, not a complete security sandbox for high-risk
tools.

## Out of scope

- Cloud or Interface implementation;
- multiple conversations with the same Ally;
- unbounded tenant concurrency;
- public Hermes access;
- a general Hermes channel plugin;
- a Postgres or Redis service for the local proof.
