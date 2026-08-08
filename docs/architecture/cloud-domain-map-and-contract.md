---
title: Cloud domain map and cross-repository contract
status: accepted handoff; implementation contracts remain gated where noted
owner: Allies Cloud and Foundry engineering
ticket: CLD-001
---

# Cloud domain map and cross-repository contract

This document is the local Cloud handoff for CLD-001. It freezes the first
managed-conversation shape without implementing the Cloud domains. It answers
three questions:

1. Which repository owns each durable fact?
2. Which product boundaries and identifiers can cross the Cloud–Foundry edge?
3. How can a message become an honest Cloud timeline without exposing runtime
   machinery or inventing a second ownership model?

The contract is transport-neutral. Provider authentication, compatibility
windows, retention values, cost caps, and the first responsibility wedge remain
open or proposed where marked below.

## 1. Status and scope

### Accepted handoff

- Cloud owns customer-facing product truth and the product API.
- Foundry owns execution truth, leases, attempts, runtime events, and private
  runtime bindings.
- Interface talks only to Cloud and reconnects with Cloud cursors.
- Cloud and Foundry do not share Django models, databases, migrations, or
  queues.
- The first Cloud product noun for the isolation boundary is `Workspace`.
- The Cloud–Foundry crossing point is a focused, versioned gateway boundary,
  not a Cloud `work` app.
- Product state and Foundry attempt state are separate state machines.
- A durable Cloud acceptance is committed before external dispatch.
- The first event payload is explicitly allowlisted and capped at 16 KiB.
- Foundry continuity and the named FND-005 through FND-008 evidence gates are
  prerequisites for Cloud implementation breadth.

### In scope

- Ownership and non-ownership of the first Cloud domains.
- Cloud and Foundry vocabulary and identifier rules.
- Authenticated and pre-auth Ally creation, claim, expiry, and cleanup seams.
- Message acceptance, idempotency, durable dispatch, event projection, state,
  and replay shapes.
- A bounded Cloud product snapshot contract separate from Foundry attempt
  replay.
- The implementation shape and evidence handoff for CLD-002 through CLD-006.

### Out of scope

- Django apps, models, migrations, controllers, workers, or production routes.
- Provider-specific authentication or transport selection.
- Foundry runtime, Hermes, Fly, or `allies-runtime` implementation.
- Billing, broad responsibility automation, a plugin marketplace, or a general
  task planner.
- Multiple conversations for one Ally.
- Generic repositories, automatic controller discovery, a central resource
  switchboard, or shared cross-repository model packages.

## 2. Ownership map

| Boundary | Owns | Must not own | Crossing rule |
| --- | --- | --- | --- |
| Interface | Rendering, local interaction state, reconnect intent, and view-model mapping | Workspace authority, Foundry credentials, Hermes sessions, runtime execution truth | Calls Cloud only; consumes Cloud IDs, product states, activities, and cursors |
| Cloud | Users, Workspaces, memberships/capabilities, Allies, conversations, messages, responsibilities, routines, approvals, and visible activities | Runtime leases, attempts, Hermes profile keys, Fly addresses, raw tool output, or private runtime event storage | Owns the product API and projection; stores only opaque Foundry binding references |
| Foundry | Runtime Workspaces, profiles, executions, attempts, leases, idempotency, Machine/volume bindings, generation fencing, and ordered runtime events | User-facing conversation wording, Cloud authorization, and Interface delivery state | Receives versioned commands and emits authenticated, correlated events |
| Hermes / runtime | Profile-local sessions, memory, tools, filesystem state, and agent execution | Cloud authorization, product delivery, and durable cross-request orchestration | Remains behind Foundry; Hermes credentials and profile keys never cross into Cloud |

Cloud is authoritative for what a person sees and changes. Foundry is
authoritative for how that work runs. A Cloud projection never claims more than
the matching Foundry evidence supports.

## 3. Proposed Cloud app homes

These names are proposed implementation homes, not empty apps to create in
CLD-001. Each app begins only when its first real feature is implemented.

| App | First responsibility | Durable nouns | Explicitly out of scope |
| --- | --- | --- | --- |
| `auths` | Actor identity, pre-auth sessions, provider handoff, and account claim | Actor, identity, `PreAuthContext`, sign-in handoff | Workspace membership or Ally data |
| `workspaces` | Cloud Workspace context and membership/capability decisions | Workspace, membership, capability context | Resource-specific business workflows |
| `allies` | Product Ally identity, purpose, and the Cloud-to-Foundry binding | Ally, job, personality seed, responsibility, routine definition, binding | Runtime profile, execution, or Hermes state |
| `chat` | One continuous customer-facing conversation per Ally | Conversation, message, intent, delivery state | Foundry attempt state or a second conversation family in v1 |
| `activities` | Safe visible product timeline projection and replay cursor | Activity, product event, feed cursor | Raw runtime event store or tool transcripts |

The gateway may live in `gateways/foundry.py` or an equivalent focused adapter
module. It is not a sixth product domain. A `work` app would obscure whether a
fact belongs to Cloud product state or Foundry execution state.

## 4. Vocabulary and identifiers

### 4.1 Vocabulary alignment

Shared words describe the crossing boundary; they do not imply shared models.

| Cloud term | Foundry term | Relationship |
| --- | --- | --- |
| Workspace | Runtime Workspace / tenant workspace | A Cloud Workspace is the customer-facing authority. Foundry's Workspace is a private one-to-one runtime binding for Machine lifecycle, generation, and leases. |
| Ally | Profile | An Ally is the product identity. A Foundry profile maps to a Hermes profile key and remains private. |
| Conversation / message | Hermes session / transcript | Cloud owns the user-facing conversation and message lifecycle. Hermes owns the local session and transcript. |
| Activity | Runtime event | Cloud projects safe product activities and assigns public feed order. Foundry keeps attempt-local event order and raw runtime payloads. |
| Routine | Execution | A routine is a future product trigger. An execution is a Foundry runtime fact; CLD-001 only reserves the source kind. |
| Auth | Runtime/service authentication | Cloud resolves actors, pre-auth principals, and claims. Foundry authenticates runtime and service calls. Credentials do not cross the product boundary. |

`Workspace` is the canonical Cloud product/API noun. Legacy `organization` or
generic `tenant` wording means Cloud Workspace when it appears in older product
planning. It is not a second domain model. Use `Foundry runtime Workspace` when
referring to the private execution boundary.

### 4.2 Public and private identifiers

| Identifier | Owner and visibility | Rule |
| --- | --- | --- |
| `cloud_workspace_id` | Cloud-generated public correlation value | Proposed grammar: `ws_` plus 26 lowercase Crockford-base32 characters. Cloud validates prefix, length, and uniqueness; Foundry treats the value as opaque. |
| `cloud_binding_id` | Cloud-owned immutable Ally binding identity | Created and persisted with the Ally before a gateway call. Every provisioning retry, claim, event mapping, cleanup operation, and reconciliation lookup uses the same value. |
| `ally_id`, `conversation_id`, `message_id`, `intent_id` | Cloud public product identifiers | Correlate product facts. They are never replaced with Foundry or Hermes identifiers. |
| `preauth_context_id` | Cloud-owned temporary context identifier | Session-bound and expiring. It is not a Workspace and carries no membership/capability semantics. |
| Operation, command, event, and dedupe IDs | Owning service | Durable, opaque, and stable across retries. Same operation identity must not be reused for a different binding or fingerprint. |
| Foundry Workspace/profile/execution/attempt IDs | Foundry-private | Resolved from the immutable binding and authenticated service context. They are not public Cloud route or response authority. |
| Hermes profile keys, session keys, credentials, Fly addresses, and raw provider output | Runtime-private | Never appear in Cloud public responses, product events, logs, or Interface contracts. |

## 5. Route and authorization matrix

A Workspace segment makes the collection and authorization boundary visible. It
does not require every nested route to repeat the Workspace ID; the service
resolves resource ancestry and rechecks capability.

| Use case | Contract shape | Authorization source |
| --- | --- | --- |
| Authenticated Ally creation | `POST /api/v1/workspaces/{cloud_workspace_id}/allies` | Actor capability in the resolved Cloud Workspace; the service rechecks ownership and lifecycle. |
| Pre-auth Ally creation | `POST /api/v1/auths/preauth/allies` | Session-bound temporary principal and `PreAuthContext`; no permanent Workspace exists yet. |
| Account claim | `POST /api/v1/auths/claims` | Authenticated actor plus the session-bound pre-auth claim context; creates a new personal Cloud Workspace. |
| Conversation message | `POST /api/v1/chat/conversations/{conversation_id}/messages` | Authenticated actor or explicitly scoped temporary principal; Cloud resolves conversation → Ally → Workspace and rechecks capability. |
| Ally activity feed | `GET /api/v1/activities?conversation_id=...&after=...` | Normal Cloud authorization for the conversation/Ally feed. |
| Cloud product snapshot | `GET /api/v1/activities/snapshots?conversation_id=...` | Normal Cloud authorization is rechecked before snapshot delivery or acceptance. |
| Background dispatch and projection | Service/gateway calls, not public routes | Persisted product context, authenticated envelope, immutable binding, correlation, and generation checks. |

Transport, credential mechanism, and exact auth-provider set remain open. HTTP
examples above are shape examples for later tickets, not CLD-001 route code.

### 5.1 Representative product shapes

These shapes make the handoff concrete without committing to final serializers
or implementation classes.

Authenticated Ally creation:

```json
{
  "name": "Review Ally",
  "job": "weekly_review",
  "personality_seed": "warm, concise, asks one question at a time",
  "idempotency_key": "client_key_..."
}
```

The response is `201` when binding is settled or `202` while provisioning is
unresolved:

```json
{
  "ally_id": "ally_...",
  "conversation_id": "conversation_...",
  "cloud_binding_id": "binding_...",
  "provisioning_operation_id": "provision_...",
  "binding_status": "pending | bound | retryable | failed"
}
```

Pre-auth creation:

```json
{
  "name": "Review Ally",
  "job": "weekly_review",
  "personality_seed": "warm, concise, asks one question at a time",
  "client_nonce": "nonce_..."
}
```

The response includes `preauth_context_id`, `ally_id`, `conversation_id`,
`cloud_binding_id`, `preauth_create_operation_id`, `greeting_status`,
`greeting_activity_id` when available, `greeting_deadline_at`,
`greeting_retry_after`, and `expires_at`.

Claim returns the same product identity and one new personal Workspace:

```json
{
  "cloud_workspace_id": "ws_...",
  "ally_id": "ally_...",
  "conversation_id": "conversation_...",
  "cloud_binding_id": "binding_...",
  "claim_operation_id": "claim_...",
  "claim_status": "claimed | already_claimed | expired | claim_repair_required"
}
```

An activity page returns ordered product activities and an opaque `next_cursor`.
An expired cursor returns `410` with `code: "cursor_expired"`,
`snapshot_required: true`, and the snapshot metadata defined in Section 12.
The client supplies no assistant-authored text for the pre-auth greeting.

## 6. Ally binding and pre-auth lifecycle

### 6.1 Authenticated Ally creation

1. Cloud validates the actor, Workspace capability, and canonical seed:
   `name`, `job`, and `personality_seed`.
2. Cloud creates the Ally and immutable `cloud_binding_id` in its transaction.
3. Cloud persists a deterministic provisioning operation, request fingerprint,
   and dispatch state before calling Foundry.
4. The binding moves through `pending` → `bound`, or to `retryable` / `failed`.
5. A same-operation, same-fingerprint retry returns the original result. A
   different fingerprint is a typed conflict; it never creates a second
   Foundry profile for the same binding.
6. Cloud may return the Ally while binding is `pending` (`202`). Reconciliation
   is by the durable operation key and binding ID, and Cloud owns repair and
   the user-visible failure state.

Foundry owns profile materialization, `soul.md`, the first-chat instruction
registry, and the opaque runtime profile reference. The shared seed contract
is the same for authenticated and pre-auth creation.

### 6.2 Pre-auth creation and greeting

`PreAuthContext` is a temporary principal, not a Cloud Workspace. It may hold
one provisional Foundry Workspace/profile binding keyed by the same immutable
`cloud_binding_id`. The context retains the new Ally, one continuous
conversation, and the first reply until claim or expiry.

The client submits `name`, `job`, `personality_seed`, and a stable,
session-bound client nonce. Cloud creates a durable `preauth_create_operation_id`
and server-creates a `preauth_greeting`; the client cannot author assistant text.
The greeting runs through Foundry/Hermes and the first Ally-authored reply is
the required first reply before sign-in.

The anonymous quota is exactly one accepted pre-sign-in reply. A failed or
timed-out greeting may retry that same intent under the bounded retry policy,
but a second anonymous user turn returns `sign_in_required` or
`quota_exhausted`. Pre-auth creation exposes `greeting_status`:
`pending`, `accepted`, `retryable`, or `failed`.

The proposed server-clock greeting budget is 120 seconds across at most two
Foundry lease windows of at most 60 seconds each. Foundry renews or
generation-fences the lease at each boundary. After at most two reconciled
retries under the same intent key, Cloud emits a typed timeout and blocks the
anonymous quota. Five pre-auth creates per session per ten minutes remains a
proposed rate/cost cap pending product and engineering approval.

### 6.3 Claim cutover

Claim and expiry are serialized by locking the `PreAuthContext`, Ally binding,
and provisioning record.

1. An authenticated actor submits a durable `claim_operation_id` and claim
   nonce.
2. If expiry has not committed, the context enters `claiming`, quiesces new
   pre-auth writes, and records a cutover marker.
3. Claim creates a new personal Cloud Workspace and adopts the same Ally,
   conversation, and immutable binding. Attaching the pre-auth Ally to an
   arbitrary existing Workspace is out of scope.
4. Already-dispatched events remain eligible by immutable binding ID while the
   outbox drains. The projector maps the pre-auth scope to the new Workspace
   before accepting Workspace-scoped events.
5. The proposed cutover drain window is 60 seconds. A missing acknowledgement
   or unsettled outbox produces `claim_repair_required`; reconciliation uses
   the same `claim_operation_id` and never creates a second Workspace or
   binding.
6. Same-fingerprint claim retries replay the original Workspace mapping;
   mismatched or cross-session claims are conflicts.

If expiry commits first, no new dispatch is accepted and claim returns
`claim_status: expired`. Late events are fenced by binding, generation, and
intent identity.

### 6.4 Expiry and cleanup

Pre-auth retention is seven days. Expiry fences pending provisioning and new
dispatch before cleanup begins:

1. Context and binding enter `cleanup_pending` under the same serialized lock.
2. Cloud sends one typed `preauth.cleanup` operation identified by
   `cleanup_operation_id`, `preauth_context_id`, and `cloud_binding_id`.
3. Foundry stops active work or fences the generation, deprovisions the
   provisional profile, and returns `deprovisioned`, `already_cleaned`, or
   `repair_required` with retry metadata and repair owner.
4. Cloud retries the same operation at most three times with bounded backoff.
   Foundry returns the original matching receipt and rejects a mismatched reuse.
5. Cloud verifies the matching receipt, purges user-visible pre-auth Ally,
   conversation, and message records, and retains only a minimal dedupe
   tombstone.
6. Cloud marks the context `cleaned` only after both sides settle. Exhaustion
   remains `repair_required`, blocks dispatch/wake, and cannot be hidden as
   success.

Late provisioning results or cleanup receipts are matched by operation,
context, and binding. They are fenced or handled idempotently and cannot
resurrect a purged context. There is no post-expiry wake.

## 7. Message acceptance and dispatch

Message acceptance is durable ingress, not execution completion.

| Function / seam | Inputs | Owns | Result |
| --- | --- | --- | --- |
| `accept_message` | Actor or `PreAuthContext`, optional Workspace, conversation, text or server-created greeting, idempotency key | Authorization, fingerprint, scope-specific idempotency, message intent, and initial scheduling state | Typed accepted/waiting result or authorization, validation, or idempotency conflict |
| `dispatch_execution_intent` | Cloud intent ID and deterministic command key | Post-commit gateway call, dispatch attempt state, timeout and reconciliation | Private Foundry reference or unresolved/retryable result; never an HTTP response |
| `project_foundry_event` | Authenticated versioned event envelope | Correlation, dedupe, claim mapping, state crosswalk, sequence recovery, and product activity allocation | Projection, typed rejection, or held sequence gap |
| `replay_ally_feed` | Authorized actor, Ally feed, opaque cursor | Retention/gap check, cutoff, ordered activities, live handoff | Activity page, bounded snapshot handoff, or cursor/scope error |
| `cleanup_preauth_context` | Locked context, binding, and cleanup operation ID | Provisioning/expiry fencing, Foundry cleanup retry, purge, tombstone, and repair owner | `deprovisioned`, `already_cleaned`, or `repair_required` |

Cloud commits the message, request fingerprint, intent, and `dispatch_pending`
state before an external call. A post-commit dispatcher derives a stable
command key from the Cloud intent ID. An unknown timeout is reconciled by that
key before retrying. An unresolved dispatch may return `202`; no response
implies execution completion.

Idempotency scope is the authority context:

- authenticated: Cloud Workspace + actor + conversation;
- pre-auth: `preauth_context_id` + conversation;
- claim: pre-auth context + claim operation, preserving lookup by immutable
  binding;
- provisioning and cleanup: the durable operation identity plus binding and
  context where applicable.

The same key and fingerprint replay the original result. The same key with a
different fingerprint is a typed `409` conflict.

An idle Ally enters `dispatch_pending` and product state `waking` immediately
after durable acceptance. When another same-Ally attempt owns the turn, the
new intent remains durable and product state is `waiting`; it does not imply
that the new turn is working or complete.

## 8. Versioned envelope and fingerprint

### 8.1 Shared base envelope

Every profile, cleanup, replay, execution, and event message inherits one
versioned base. Specialized payloads may add typed fields but cannot bypass
the shared scope, authentication, dedupe, deadline, or replay rules.

| Field | Rule |
| --- | --- |
| `schema_version`, `kind`, `producer` | Required version and discriminant; Cloud and Foundry validate the producer they receive. |
| `service_identity` | Required authenticated service identity; never inferred from caller-supplied runtime scope. |
| Operation/command/event identity | Required stable identity for the message class. |
| `idempotency_key` or `dedupe_key` | Required where the message can be retried or replayed. |
| Cloud correlation | Cloud intent/message/conversation/Ally identifiers as applicable. |
| `cloud_binding_id` | Required immutable binding correlation. |
| `scope` | Required discriminated Workspace or pre-auth variant. |
| `created_at`, `deadline_at` | Server-clock timing fields; excluded from the fingerprint projection. |
| `fingerprint` | `canonical-json-sha256:v1` over the stable typed projection below. |

The scope is discriminated, and the unused variant is omitted rather than
sent as `null`:

```json
{ "kind": "workspace", "cloud_workspace_id": "ws_..." }
```

or:

```json
{ "kind": "preauth", "preauth_context_id": "preauth_..." }
```

Workspace mode forbids `preauth_context_id`; pre-auth mode forbids
`cloud_workspace_id`. The private Foundry Workspace ID is never carried.

### 8.2 Canonical fingerprint

For each message class, the hash input is the typed body projection containing:

- `schema_version` and `kind`;
- the discriminated `scope`;
- stable Cloud correlation fields;
- immutable `cloud_binding_id`;
- operation/idempotency identity or event identity;
- the specialized typed payload.

The projection excludes `fingerprint`, `created_at`, `deadline_at`, receipt
timestamps, retry counters, and transport headers. Serialization is:

1. normalize strings to NFC;
2. sort object keys;
3. use compact separators with no insignificant whitespace;
4. escape non-ASCII characters using ASCII JSON escaping;
5. reject NaN and infinity (`allow_nan=false`);
6. encode the result as UTF-8 bytes;
7. SHA-256 the bytes and label it `canonical-json-sha256:v1`.

Cross-language fixtures must cover profile provisioning, cleanup, replay, and
event retry. The same operation key must produce the same projection before a
replay. Changing this serializer or projection is a versioned contract change.

### 8.3 Reciprocal validation

Foundry rejects commands with invalid service identity, binding, dedupe key,
scope, or caller-supplied profile/attempt/generation authority. Cloud rejects
events with invalid service identity, binding, correlation, generation,
dedupe identity, event sequence, unknown kind/field, secret-bearing payload, or
oversize payload. Each side derives private runtime scope from authenticated
records rather than trusting repeated caller fields.

## 9. Command and event shapes

These are transport-neutral v1 shapes. Transport, credentials, and the
compatibility window remain open.

### 9.1 Execution command

```json
{
  "schema_version": "v1",
  "kind": "execution.command",
  "producer": "cloud",
  "service_identity": "cloud-service",
  "command_id": "cmd_...",
  "idempotency_key": "intent_...",
  "scope": { "kind": "workspace", "cloud_workspace_id": "ws_..." },
  "cloud": {
    "ally_id": "ally_...",
    "conversation_id": "conversation_...",
    "message_id": "message_...",
    "intent_id": "intent_...",
    "cloud_binding_id": "binding_..."
  },
  "source_kind": "conversation_message",
  "payload": { "kind": "execution_input", "text": "..." },
  "created_at": "server-time",
  "deadline_at": "server-time",
  "fingerprint": "canonical-json-sha256:v1:..."
}
```

Allowed `source_kind` values are `conversation_message`,
`preauth_greeting`, and the reserved future value `routine`. Routine
scheduling is not implemented in CLD-001.

### 9.2 Event envelope

```json
{
  "schema_version": "v1",
  "kind": "execution.event",
  "producer": "foundry",
  "service_identity": "foundry-service",
  "event_id": "event_...",
  "event_dedupe_key": "execution:attempt:generation:event",
  "scope": { "kind": "workspace", "cloud_workspace_id": "ws_..." },
  "cloud": {
    "ally_id": "ally_...",
    "conversation_id": "conversation_...",
    "intent_id": "intent_...",
    "cloud_binding_id": "binding_..."
  },
  "foundry": {
    "execution_id": "private-ref",
    "attempt_id": "private-ref",
    "generation": "generation-ref",
    "attempt_sequence": 7
  },
  "event_type": "assistant.message",
  "payload": { "kind": "product_message", "visibility": "user", "text": "..." },
  "created_at": "server-time",
  "deadline_at": "server-time",
  "fingerprint": "canonical-json-sha256:v1:..."
}
```

The example uses placeholders for private Foundry fields; those fields remain
inside the authenticated Cloud–Foundry boundary and never appear in public
Cloud responses.

## 10. Event safety and projection

The v1 product-safe event registry is explicit:

| Event kind | Allowed fields |
| --- | --- |
| `assistant.message` | `kind`, `visibility`, `text`, optional `product_message_id` |
| `activity.state` | `kind`, `product_state` |
| `approval.requested` | `kind`, `approval_id`, `prompt` |
| `execution.terminal` | `kind`, `status`, `reason` |

Unknown event kinds and fields, raw secrets, provider credentials, runtime
identifiers, unregistered prompts, and payloads over 16 KiB are rejected with
typed errors. Only explicitly registered provider-metadata values may be
replaced with the literal `[redacted]`; unknown fields are never silently
redacted. Any registry or payload-cap change is an explicit FND-007 contract
prerequisite.

Event dedupe identity is the composite:

```text
execution_id + attempt_id + generation + event_id
```

It matches Foundry's attempt-scoped uniqueness. Duplicate events reuse the
original Cloud activity sequence. Wrong Workspace, Ally, conversation, intent,
binding, generation, or attempt events are rejected and do not advance the
Cloud cursor.

## 11. Product state and runtime state

Cloud names the user-facing state. Foundry keeps the private execution state.
`message accepted` is an ingress result, not a product lifecycle state.

### 11.1 Cloud state vocabulary

Cloud presentation includes `sleeping` as the normal idle baseline and uses
these active/terminal values in the contract:

```text
waking | waiting | working | waiting_for_approval |
completed | stopped | retryable | failed | repair_required
```

`claim_repair_required` is a claim-operation result, not a runtime product
state. No terminal state implies success without reconciled evidence.

### 11.2 Crosswalk

| Foundry evidence | Cloud product state | Projection rule |
| --- | --- | --- |
| Durable Cloud intent accepted while idle; `dispatch_pending` | `waking` | Expose immediately; gateway acknowledgement is not required to show that the Ally is being woken. |
| Queued/leased attempt with an active same-Ally turn | `waiting` | Keep the durable message queued behind the active turn. |
| Acknowledged current-generation running execution | `working` | Requires a matching execution/attempt/generation acknowledgement. |
| Allowlisted approval-required event | `waiting_for_approval` | Project approval activity only; never imply completion. |
| Matching succeeded terminal event and contiguous sequence | `completed` | Require terminal evidence for the matching execution, attempt, and generation. |
| Matching cancellation with stop acknowledgement | `stopped` | A request without stop/fence acknowledgement remains active or becomes repair-required. |
| Safe failure with no newer active generation and a safe command key | `retryable` | Retry only after Foundry confirms the prior generation is fenced or terminal. |
| Matching failed terminal event | `failed` | Require terminal evidence; duplicate terminal events are idempotent. |
| Unknown attempt, unresolved lease/generation, retention gap, or unsafe retry | `repair_required` | Hold the last truthful state, assign repair ownership, and never auto-claim success. |

Foundry's current attempt and lease enums remain authoritative at the gateway.
Lease expiry without stop/fence acknowledgement is `repair_required`, not an
automatic wake or retry. A sequence gap holds the last truthful state until
replay or an explicit typed repair outcome.

### 11.3 State transitions

```text
sleeping -> waking: durable message accepted while idle
sleeping -> waiting: message accepted behind an active same-Ally attempt
waking -> working: current-generation execution acknowledged
waking -> waiting: another same-Ally turn is queued
working -> waiting_for_approval: approval projection
working -> completed | stopped | retryable | failed: reconciled evidence
retryable -> waking: explicit safe retry
completed | stopped | failed -> sleeping: terminal state settled
any active state -> repair_required: unsafe or unknown reconciliation
```

Different Allies may be active concurrently. Only turns for the same Ally are
serialized in the initial product.

## 12. Replay, cursor, and snapshot recovery

### 12.1 Cloud feed

The first cursor scope is one Ally feed; conversation routes resolve that feed.
Cloud allocates a unique monotonic product sequence in the same transaction as
the activity projection. Rollback persists neither the activity nor its
sequence. Concurrent projections serialize on the feed, and a duplicate event
reuses its original sequence.

The opaque versioned cursor contains feed scope and sequence internally. A
live subscription uses the same cutoff as replay: replay includes the range
through the inclusive cutoff, and live delivery resumes strictly after it.

### 12.2 Foundry attempt replay

Foundry owns a separate transport-neutral `execution.replay` seam:

```json
{
  "kind": "execution.replay",
  "replay_operation_id": "replay_...",
  "cloud_binding_id": "binding_...",
  "execution_id": "private-ref",
  "attempt_id": "private-ref",
  "generation": "generation-ref",
  "from_sequence": 8,
  "to_sequence": 12,
  "max_events": 100
}
```

Receipts are `replayed`, `retention_gap`, `timeout`, or `repair_required` and
carry the same operation identity. Cloud keeps the last contiguous cursor and
does not advance it over a gap. A retention gap or timeout produces a typed
repair activity or requires a Cloud snapshot/operator repair.

### 12.3 Cloud product snapshot

Cloud cursor expiry is a product-feed contract, not raw Foundry replay. An
authorized snapshot is bounded to at most 200 activities and 256 KiB:

```json
{
  "snapshot_id": "snapshot_...",
  "snapshot_version": "v1",
  "snapshot_digest": "sha256:...",
  "cutoff_sequence": 42,
  "activities": [],
  "next_cursor": "cursor_..."
}
```

The supplied cursor is exclusive. The snapshot includes activities through the
inclusive `cutoff_sequence`; live resume starts strictly after that cutoff.
The `410` cursor-expired result carries the same snapshot metadata and
`snapshot_required`. Cloud validates feed scope, normal authorization,
snapshot version, digest, cutoff, and resume cursor before accepting the
snapshot.

## 13. Profile seed and first-chat ownership

Cloud sends one versioned `profile.provision` request for authenticated and
pre-auth creation:

```json
{
  "kind": "profile.provision",
  "provisioning_operation_id": "provision_...",
  "cloud_binding_id": "binding_...",
  "preauth_context_id": "preauth_...",
  "seed": {
    "name": "Review Ally",
    "job": "weekly_review",
    "personality_seed": "warm, concise, asks one question at a time",
    "first_chat_instruction_version": "registry-v1",
    "first_chat_instruction_hash": "sha256:..."
  }
}
```

`preauth_context_id` is present only for the pre-auth variant; authenticated
Workspace-scoped provisioning omits it rather than sending `null`.

Foundry is the sole resolver and validator for the first-chat instruction
registry. A registry entry publishes a version, compatibility window, and
SHA-256 over exact UTF-8 instruction-template bytes before runtime
interpolation. Cloud persists the returned version/hash and never invents a
template. The receipt proves `instruction_materialized_once=true` on replay,
and the exact user personality text is preserved.

Profile provisioning returns `pending`, `bound`, `incompatible`, or
`repairable` with an opaque profile reference kept inside the gateway. The
CLD-003 implementation and pre-auth greeting are gated on FND-006 evidence.

## 14. Future implementation shape

The first real app starts with folders for `services/` and
`api/controllers/`. Add queries, tasks, events, handlers, or gateway
submodules only when a concrete boundary earns them.

| Use case | Initial owner | Contract responsibility |
| --- | --- | --- |
| `accept_message` | `chat` service | Authorization, transaction, fingerprint, idempotency, and scheduling state |
| `dispatch_execution_intent` | Cloud service + focused Foundry gateway | Commit-before-call, deterministic command key, timeout, and reconciliation |
| `project_foundry_event` | `activities` service/projector | Authenticated envelope, composite dedupe, state crosswalk, gap recovery, and Cloud feed sequence |
| `replay_ally_feed` | `activities` read service | Authorization, cursor retention, cutoff, ordered activities, snapshot handoff |
| `cleanup_preauth_context` | `auths`/binding service boundary | Serialized expiry, cleanup receipt, purge/tombstone, fencing, and repair owner |

Controllers remain HTTP adapters. Services own transactions and domain
errors. Queries are optional. API registration is explicit through the root
`/api/v1/` API. No controller calls Foundry directly, and no Cloud domain
imports Foundry models.

## 15. Foundry dependency gates

Cloud implementation breadth stays gated until the following evidence exists:

| Gate | Required evidence | Cloud consequence |
| --- | --- | --- |
| FND-005 leases and fencing | Profile-scoped lease serialization, tenant generation fencing, cancellation acknowledgement, and retryable expiry behavior | Cloud can rely on Foundry to reject stale execution mutations. |
| FND-006 profile provisioning/deprovisioning | Versioned seed handoff, `soul.md` materialization, deterministic provisioning, idempotent receipt, incompatible/repairable outcomes, provisional cleanup, and late-result fencing | CLD-003 and pre-auth greeting can bind one Ally without inventing runtime identity or cleanup semantics. |
| FND-007 sessions and events | Versioned execution command, immutable Cloud correlation, ordered attempt events, effective Hermes session update, safe terminal events, 16 KiB allowlist, and replay/snapshot receipt | CLD-005/CLD-006 can project and recover without copying Hermes state. |
| FND-008 continuity proof | Two isolated Ally profiles resume across Machine replacement with the same durable volume | Managed-conversation implementation breadth may begin. |
| Joint gateway contract | Version owner, compatibility policy, service authentication, command/event envelope, dedupe, and fallback behavior | Cloud and Foundry implement against a stable seam rather than a speculative client. |

Until these gates pass, this document remains a contract handoff and Cloud
should not promise runtime behavior it cannot prove.

## 16. Open, proposed, and deferred choices

| Item | Status | Next owner/evidence |
| --- | --- | --- |
| Cloud Workspace noun and five app homes | Accepted noun; app homes proposed | Cloud engineering keeps names aligned as each real feature begins. |
| Pre-auth provisional binding, immutable identity, claim-to-new-Workspace, and cleanup receipt | Accepted contract safeguards; detailed runtime receipt remains gated | Cloud + Foundry implement against FND-006 evidence. |
| `cloud_workspace_id` grammar | Proposed v1 shape | Cloud/Foundry contract owners approve before gateway implementation. |
| v1 event registry, conditional scope, fingerprint, 16 KiB cap, and snapshot bounds | Proposed versioned contract shape for implementation handoff | Joint gateway owners publish fixtures and compatibility policy. |
| Greeting 120-second budget, two lease windows, 60-second claim drain, and three cleanup retries | Proposed operational defaults | Product, Cloud Auth, and Foundry Runtime approve cost, retry, and repair ownership. |
| Auth provider set, pre-auth principal/token rotation, and cross-session replay protection | Open | Product and Cloud Auth before `auths` implementation. |
| Cloud-to-Foundry physical transport and service credential mechanism | Open | Cloud + Foundry after FND-007 evidence. |
| Compatibility window and schema/version ownership | Open | Joint gateway owners before CLD-005. |
| Cloud and Foundry event retention period | Open | Cloud + Foundry after measured storage/reconnect requirements. |
| First responsibility wedge and routine scheduling | Open/deferred | Product owner before CLD-003/CLD-004; `routine` remains only a reserved source kind here. |

No open choice may be silently settled by a later implementation ticket. A
material change to ownership, public identifiers, state truth, or the
cross-repository envelope requires its own reviewed plan revision.

## 17. CLD-001 acceptance and validation

CLD-001 is complete when:

- a new engineer can trace each durable fact to Interface, Cloud, Foundry, or
  Hermes/runtime ownership;
- five proposed Cloud app homes and the Workspace route strategy are explicit;
- public shapes contain no Hermes secrets, profile keys, runtime addresses, or
  private runtime authority;
- pre-auth seed, server-created greeting, claim replay, expiry cleanup,
  operation receipts, and immutable binding identity are concrete;
- message acceptance, dispatch recovery, event projection, state mapping,
  cursor sequencing, and bounded snapshot recovery are concrete;
- the exact fingerprint and event-safety rules are written down;
- Foundry gates and unresolved decisions are visible; and
- this contract stays one reviewable Cloud change, with later CLD tickets in
  separate kickoffs, worktrees, and PRs.

This documentation slice is validated with:

```text
make check
make lint
make test
git diff --check
```

Later implementation tickets add API, service, gateway, projection, replay,
authorization, cross-language fixture, and failure-path tests named by this
contract. CLD-001 creates no Django model or migration.

## 18. Source handoff

The contract was reconciled against:

- `docs/engineering/backend-development.md`;
- `ENGINEERING_STYLE.md` and the Cloud scaffold;
- the accepted CLD-001 brief and Lavish plan;
- final adversarial review v9 and simplicity review v10;
- Allies architecture, decision log, conversation/streaming specification,
  Foundry continuity specification, product requirements, and MVP roadmap in
  Nabu under `projects/allies`;
- the local managed-conversation epic and downstream CLD ticket sequence.

Nabu remains the canonical evolving Allies knowledge space. This PR does not
publish or mutate Nabu; the revision-aware Nabu handoff is required only when
implementation materially changes an accepted architecture decision.
