# routines-v1 contract

Status: normative Cloud artifact for CLD-012. This file describes a versioned
boundary only; it does not add routes, models, migrations, schedulers, or
runtime handlers.

## Identity and ownership

The identity tuple is kept in `routines-v1.lock.json` and is:

```text
contract_name=routines
schema_version=v1
content_revision=14
content_sha256=<SHA-256 of this exact file>
fixture_sha256=<SHA-256 of fixtures/routines-v1.json>
```

Cloud is the normative owner. Foundry vendors the exact bytes for compatibility
and must not publish an independently edited copy. The byte rules are UTF-8,
no BOM, LF line endings, and one final newline. The lock file is outside both
hashes so the identity is not self-referential.

Cloud owns routine records, scheduling, owner authorization, discovery, user
approval projection, and insertion of attributed results into the main chat.
Foundry owns profiles, executions, attempts, leases, runtime sessions, and
ordered runtime events. No repository imports the other repository's models.

Every routine belongs to exactly one workspace, owner, Ally, and Cloud binding.
The following opaque UUIDs are immutable correlation fields once persisted:

| Identity | Owner | Meaning |
| --- | --- | --- |
| `workspace_id` | Cloud | Tenant boundary for the routine and its owner |
| `owner_user_id` | Cloud | Authorized human owner; never model-supplied authority |
| `ally_id` | Cloud | Responsible Ally and authorized resource scope |
| `routine_id` | Cloud | Stable routine identity |
| `occurrence_id` | Cloud | One scheduled opportunity; survives transport retries |
| `run_id` | Cloud | One execution of an occurrence |
| `main_conversation_id` | Cloud | Existing conversation that receives attributed results |
| `run_conversation_id` | Cloud | Fresh conversation for this occurrence |
| `cloud_binding_id` | Cloud/Foundry | Immutable gateway binding correlation |
| `execution_id` | Foundry | Runtime execution identity |
| `attempt_id` | Foundry | One fenced runtime attempt |
| `generation` | Foundry | Monotonic worker/lease fence |
| `event_sequence` | Foundry | Strictly increasing attempt event sequence |

`main_conversation_id`, `run_conversation_id`, and `execution_id` are always
different. A routine may run concurrently with main chat and another routine,
but one routine never has two active runs and existing same-conversation turn
serialization remains in force.

## Common envelope and canonical identity

Routine messages use the existing v1 transport envelope shape. Every routine
message has `schema_version: "v1"`, a closed `kind`, `producer`,
`service_identity`, the direction-appropriate command or event replay identity,
the exact trusted `scope`, `issued_at`, `deadline_at`, and a canonical
fingerprint. Existing `execution.command` messages with
`source_kind: "conversation_message"` are unchanged. An old consumer rejects
an unsupported routine kind with a safe validation error; it does not
reinterpret it as a conversation message.

For fingerprint vectors, canonical JSON is sorted-key, compact JSON with ASCII
escaping, no insignificant whitespace, finite numbers only, and UTF-8 bytes.
The digest is `canonical-json-sha256:v1:<64 lowercase hex characters>`. The
logical fingerprint excludes `fingerprint`, `issued_at`, and `deadline_at`.
Retry timestamps may change without changing semantic identity. Unknown fields
are rejected at each future typed boundary. The fixture checks this canonical
algorithm and metadata only; it is not a validator or state-machine engine.

Fixture messages use the following direction-specific authenticated envelopes:

- Cloud commands (`routine.manage`, `routine.dispatch`,
  `routine.approval_decision`, and `routine.cancel_wait`) use `producer:
  "cloud"`, `service_identity: "cloud-service"`, `command_id`,
  `idempotency_key`, the complete trusted workspace scope, `issued_at`,
  `deadline_at`, and `fingerprint`.
- Foundry events use `producer: "foundry"`,
  `service_identity: "foundry-service"`, `event_id`, `event_sequence`, the
  complete trusted workspace scope, `issued_at`, `deadline_at`, and
  `fingerprint`. The event ID and sequence are the replay identity; event
  delivery retries do not invent a new event. The fixture uses this direction
  for `routine.result` and `routine.approval_requested`.
- Responses and receipts use the producing service's identity, echo the
  initiating command or event identity and replay key, and carry the same
  scope plus their own `issued_at`, `deadline_at`, and `fingerprint` fields.
  A result ingestion receipt echoes `event_id` and `event_sequence`; command
  receipts and management responses echo `command_id` and `idempotency_key`.

Every fixture `scope` is the exact trusted scope from `common.scope`, including
its `kind`, workspace, owner, Ally, and Cloud binding. The existing
`execution.command` envelope with `source_kind: "conversation_message"` remains
unchanged.

Current transport bounds remain in force: command lifetime is at most 60
seconds, prompt/text is at most 16 KiB UTF-8, an event envelope is at most 64
KiB, and event sequence budgets remain those of the existing v1 contract. A
routine's 24-hour human approval wait is a durable state, not a relaxation of
the transport deadline.

## Closed vocabularies

Management operations are `create`, `update`, `pause`, `resume`, `delete`,
`get`, and `list`. Schedule states are `active`, `paused`, `deleted`, and
`exhausted`. Schedule kinds are `once` and `recurring`. Occurrence dispositions
are `admitted`, `replay`, `skipped_active`, `delayed`, `recovered`, and
`cancelled`. Run outcomes are `queued`, `working`, `approval_waiting`,
`succeeded`, `failed`, `cancelled`, and `expired`. Result outcomes are `changed`,
`unchanged`, and `failed`. Approval decisions are `approve` and `reject`.

Action-attempt states are `pre_dispatch`, `dispatching`, `completed`, `unknown`,
and `manual_reconciliation`; they are monotonic. They are contract vocabulary,
not new tables in CLD-012.

## Management and discovery

`routine.manage` is the logical Cloud command. It carries the common envelope,
trusted workspace/owner/Ally/binding scope, `operation`, and an operation
specific body:

| Operation | Required body | Nullable/omitted fields | Result |
| --- | --- | --- | --- |
| `create` | `title`, full `execution_prompt`, `schedule` | none | Saved detail with revision 1 |
| `update` | `routine_id`, `expected_revision`, changed `title`/prompt/schedule | unchanged fields may be omitted; null is not a delete signal | New saved detail and revision |
| `pause` | `routine_id`, `expected_revision` | none | Paused detail; recurring schedule retained |
| `resume` | `routine_id`, `expected_revision` | none | Active detail with next future occurrence |
| `delete` | `routine_id`, `expected_revision`, exact conversational `confirmation_ref` | none | Deleted receipt; no future admission |
| `get` | `routine_id` | none | Authorized full detail |
| `list` | owner/filter-bound opaque `cursor`, bounded `limit` | cursor may be null on first page; `ally_id` may be omitted | Page without full prompt |

`title` is a short display label; `execution_prompt` is the complete
Ally-authored task and is never truncated. A sufficiently specified user
instruction can create immediately. A suggestion needs user agreement, and a
missing task, timing, or IANA timezone is clarified before persistence.
Delete confirmation is tied to the exact routine and expected revision.

The deletion confirmation boundary is Cloud-owned (V14 / Phase-2). A Cloud
confirmation challenge has this shape:

```json
{
  "confirmation_ref": "<opaque one-shot reference>",
  "scope": {
    "kind": "workspace",
    "workspace_id": "<workspace UUID>",
    "owner_user_id": "<owner UUID>",
    "ally_id": "<Ally UUID>",
    "cloud_binding_id": "<binding UUID>"
  },
  "main_conversation_id": "<main conversation UUID>",
  "routine_id": "<routine UUID>",
  "expected_revision": 4,
  "state": "unconsumed"
}
```

`confirmation_ref` is the only confirmation field transported in a
`routine.manage` delete request. Web, native, client, and integration layers
may carry it only in the authenticated request and must preserve it as an
opaque value; they must not decode, validate, issue, bypass, log, or trace the
raw capability. If operational correlation is required, logs and traces may
contain only a non-reversible keyed digest such as
`HMAC-SHA-256(telemetry_key, confirmation_ref)` under a service-held key, never
the raw value, a reversible encoding, or an unkeyed digest. Cloud/CLD-013
validates that the reference is present and unconsumed and that its scope,
issuing `main_conversation_id`, `routine_id`, and `expected_revision` exactly
match the authorized delete and current routine. Successful validation marks
the reference consumed and CAS-deletes the routine in the same transaction;
the transaction commits one durable `MANAGEMENT_SAVED` receipt or mutates
neither the routine nor the reference.

Rejected confirmation vectors are explicit and do not burn a valid reference:

| Vector | Result code | Required state effect |
| --- | --- | --- |
| Missing reference | `CONFIRMATION_REQUIRED` | Zero routine mutation; no reference is consumed |
| Stale expected revision | `CONFIRMATION_STALE` | Zero routine mutation; stale reference remains unconsumed |
| Replayed reference | `CONFIRMATION_REPLAYED` | Zero routine mutation; already-consumed reference remains consumed |
| Foreign main conversation | `CONFIRMATION_WRONG_CONVERSATION` | Zero routine mutation; foreign reference remains unconsumed |
| Foreign owner scope | `CONFIRMATION_WRONG_OWNER` | Zero routine mutation; foreign reference remains unconsumed |
| Foreign workspace scope | `CONFIRMATION_WRONG_WORKSPACE` | Zero routine mutation; foreign reference remains unconsumed |
| Foreign Ally scope | `CONFIRMATION_WRONG_ALLY` | Zero routine mutation; foreign reference remains unconsumed |
| Foreign Cloud binding | `CONFIRMATION_WRONG_BINDING` | Zero routine mutation; foreign reference remains unconsumed |
| Cross-routine reference | `CONFIRMATION_WRONG_ROUTINE` | Zero routine mutation; cross-routine reference remains unconsumed |

This V14 / Phase-2 split is normative: Cloud/CLD-013 owns challenge issuance,
exact-binding validation, atomic consumption, and deletion CAS; downstream
Web/native/client/integration boundaries own only authenticated opaque-reference
transport and digest-only trace propagation. A rejected foreign caller cannot
consume a valid challenge, raw confirmation capabilities never enter downstream
logs or traces, and no rejected vector returns a successful management receipt.

Every successful mutation returns a durable `ManagementReceipt` with
`outcome: "saved"`, `operation`, `routine_id`, `revision`, and the resulting
schedule state. `MANAGEMENT_SAVED` is the stable success code for the create,
update, pause, and delete receipt examples. Resume retains its
operation-specific `ROUTINE_RESUMED` code while carrying the same durable
saved-receipt semantics. Acceptance or a pending outbox is not persisted
success. `REVISION_CONFLICT`, `ROUTINE_DELETED`, `ROUTINE_PAUSED`, and
`STALE_DUE_CANDIDATE` remain separate stale, candidate, or race outcomes and
must not be used as successful mutation receipts.

`RoutineDetail` includes `routine_id`, `revision`, title, full prompt, schedule,
responsible Ally, `schedule_state`, nullable `next_run_at`, and owner scope.
`RoutinePage` includes at most 100 items (default 50), an opaque cursor, and
items without full prompt. Order is `(created_at, routine_id)` keyset order;
the owner and filter are bound to the cursor and rechecked on every page.
Changes between pages are not a snapshot promise. Paused recurring routines
remain discoverable even without `next_run_at`; deleted, exhausted, and
finished one-time schedules are excluded regardless of run outcome.

## Schedule and timezone

Wire instants have second precision and UTC `Z` form. A one-time schedule is:

```json
{"kind":"once","local_at":"2026-09-10T09:00:00","timezone":"Europe/Berlin"}
```

A recurring schedule uses this closed grammar:

```json
{"kind":"recurring","frequency":"weekly","local_time":"09:00:00",
 "days_of_week":[1,3,5],"timezone":"Europe/Berlin"}
```

`frequency` is `daily`, `weekly`, or `monthly`. Daily omits `days_of_week` and
monthly requires one `day_of_month` from 1 through 31; weekly requires a
non-empty ascending list of ISO weekdays 1 through 7. All recurring schedules
require `local_time` and an IANA timezone. Unsupported cadence is rejected,
not approximated. Browser/device timezone is used only when the user explicitly
saves it; a missing timezone is clarification.

The saved timezone remains fixed until explicit update. A DST gap advances to
the next valid local instant. A repeated wall time runs once at the earliest
instant (`fold=0`). Recovery admits the latest missed recurring occurrence once
or a missed one-time occurrence once and marks it visibly delayed. Intentionally
paused/skipped occurrences are never replayed. Resume computes the first
scheduled instant strictly after the Cloud database-clock resume boundary.

## Dispatch and context

`routine.dispatch` is a Cloud-to-Foundry logical command with an immutable
snapshot of routine revision, title, full prompt, saved schedule/timezone,
scheduled UTC instant, owner/Ally/binding, `occurrence_id`, `run_id`, both
conversation IDs, `main_conversation_id`, and `occurrence_disposition`.
Cloud creates the occurrence, unique routine+scheduled-instant identity, run
snapshot, and dispatch outbox intent in one short transaction. No network call
is made inside that transaction. The accepted receipt means execution was
accepted, not completed.

Cloud's dispatch command carries the routine, occurrence, revision, and schedule
generation snapshot. Foundry assigns `execution_id`, `attempt_id`, and
`generation`; those identities first appear in the dispatch receipt and ordered
events, not in the Cloud command.

The occurrence gets a fresh run conversation with the same profile identity,
memory, files, and authorized tools. Main or prior-run transcripts are not
copied automatically. Edits, pause, and delete affect future admissions and do
not rewrite an already working snapshot. An explicit user retry has a new
linked execution identity; a delivery retry reuses the occurrence identity.

## Results, main-chat insertion, and approval

Foundry emits ordered `routine.result` and `routine.approval_requested` events. A result
contains immutable correlation, required `routine_revision` and `title_snapshot` fields
copied exactly from its accepted dispatch, `outcome`,
bounded result text, `delayed`, and typed references such as
`{"label":"document","url":"https://example.test/document"}`. Credentials,
tool grants, arbitrary hidden notes, full transcripts, and run-inspection URLs
are not contract fields. Every completed run, including `unchanged`, and every
failure produces an attributed main-chat result, and results survive routine
deletion.

Cloud durably ingests the event once, then inserts the result at a main-turn
boundary after an active main turn and before dispatch of the next turn. The
insertion receipt/watermark is durable and deduplicated. A queued user turn must
include the result in actual model input/history once it is inserted; a UI-only
message is insufficient. An in-flight model prompt is never changed. Pending
insertion remains pending and is truthful in the receipt.

`routine.approval_requested` identifies the same run, attempt, generation, and
one-shot action permission. Foundry's database clock creates `created_at` and
`expires_at = created_at + 24h` after the relevant locks. At decision time one
CAS requires pending status, unconsumed permission, matching immutable identity,
current generation, `approval_waiting`, and database `now < expires_at`; it then
records the decision, consumes permission, and changes the run to `working` in
one transaction. Equality with expiry rejects approval. The 60-second transport
deadline remains separate.

The action-attempt identity is immutable. It moves
`pre_dispatch -> dispatching -> completed`, or
`dispatching -> unknown -> completed/manual_reconciliation`. An ambiguous
external result is reconciled by at most three read-only status lookups within
60 seconds. Only a verified provider idempotency guarantee permits a same-key
recovery call. There is no non-idempotent replay or whole-prompt restart.

Approval, expiry, rejection, and replacement cancellation are serialized at
Foundry. Approval already authorizing work wins and the next occurrence skips;
effective cancellation/expiry invalidates the old decision and replacement
dispatch waits for a fencing receipt. Rejected, expired, cancelled, and
manual-reconciliation outcomes reach main chat.

## Lifecycle, errors, and race rules

Schedule state, occurrence disposition, run outcome, and action-attempt state
are separate. Terminal run outcomes never reopen. A recurring failure does not
pause its schedule or automatically rerun the task. Safe transport and
reconciliation retries are bounded.

Every due candidate carries `observed_revision` and
`observed_schedule_generation`. Cloud increments the generation on schedule or
timezone changes and effective pause/resume. A newly created routine starts at
generation `1`, and each such transition increments it exactly once. Admission locks the routine,
rechecks both values and state, and returns `STALE_DUE_CANDIDATE` with zero
write when either changed. Resume stores a database-clock boundary and chooses
the strictly next future instant; repeated resume is `ROUTINE_ALREADY_ACTIVE`.

The following result codes are stable contract evidence. They are not
implemented responses in CLD-012.

| Code | Future enforcing owner | Meaning |
| --- | --- | --- |
| `INVALID_INPUT` | CLD-013 | Closed shape, bound, timezone, or schedule failure |
| `NOT_FOUND` | CLD-013 | Owner-scoped object is absent or unauthorized |
| `REVISION_CONFLICT` | CLD-013 | Expected revision is stale; zero mutation |
| `MANAGEMENT_SAVED` | CLD-013 | Management mutation durably saved and returned as a receipt |
| `CONFIRMATION_REQUIRED` | CLD-013 | Delete confirmation reference is missing; zero mutation |
| `CONFIRMATION_STALE` | CLD-013 | Delete confirmation targets a stale expected revision; zero mutation |
| `CONFIRMATION_REPLAYED` | CLD-013 | Delete confirmation was already consumed; zero mutation |
| `CONFIRMATION_WRONG_CONVERSATION` | CLD-013 | Delete confirmation is bound to another main conversation; zero mutation |
| `CONFIRMATION_WRONG_OWNER` | CLD-013 | Delete confirmation is outside the authorized owner scope; zero mutation |
| `CONFIRMATION_WRONG_WORKSPACE` | CLD-013 | Delete confirmation is bound to another workspace; zero mutation |
| `CONFIRMATION_WRONG_ALLY` | CLD-013 | Delete confirmation is bound to another Ally; zero mutation |
| `CONFIRMATION_WRONG_BINDING` | CLD-013 | Delete confirmation is bound to another Cloud binding; zero mutation |
| `CONFIRMATION_WRONG_ROUTINE` | CLD-013 | Delete confirmation is bound to another routine; zero mutation |
| `ROUTINE_DELETED` | CLD-013 | Candidate/mutation observes deleted routine |
| `ROUTINE_PAUSED` | CLD-013 | Candidate observes paused recurring routine |
| `PAUSE_UNSUPPORTED` | CLD-013 | One-time routine cannot be paused |
| `CANDIDATE_SUPERSEDED` | CLD-013 | Candidate no longer represents current schedule |
| `STALE_DUE_CANDIDATE` | CLD-013 | Revision/generation fence changed; zero occurrence/outbox |
| `NOT_DUE` | CLD-013 | Candidate is not strictly eligible at admission |
| `ROUTINE_RESUMED` | CLD-013 | Pause-to-active transition committed |
| `ROUTINE_ALREADY_ACTIVE` | CLD-013 | Idempotent resume no-op |
| `OCCURRENCE_ADMITTED` | CLD-013 | One immutable occurrence/run/outbox committed |
| `OCCURRENCE_REPLAY` | CLD-013 | Same occurrence returns its stored snapshot/receipt |
| `OCCURRENCE_SKIPPED_ACTIVE` | CLD-013 | Same-routine work is active; no backlog |
| `REPLACEMENT_PENDING` | integration | Waiting run needs effective cancellation before replacement |
| `APPROVAL_AUTHORIZED` | FND-012 | Permission consumed and action authorizing/working |
| `APPROVAL_REJECTED` | FND-012 | Rejection consumed permission and terminalized run |
| `APPROVAL_EXPIRED` | FND-012 | Database clock reached deadline |
| `APPROVAL_CANCELLED` | FND-012 | Replacement/expiry cancellation fenced old work |
| `APPROVAL_ALREADY_AUTHORIZING` | FND-012 | Competing decision lost to authorization |
| `STALE_GENERATION` | FND-012 | Old attempt/lease cannot act or project |
| `CORRELATION_MISMATCH` | FND-012 | Immutable identity tuple differs |
| `IDEMPOTENCY_CONFLICT` | FND-012 | Same key carries a different semantic fingerprint |
| `ACTION_OUTCOME_UNKNOWN` | FND-012 | External effect may have occurred; no safe receipt |
| `ACTION_MANUAL_RECONCILIATION` | FND-012 | Automatic processing stops pending human/provider reconciliation |
| `RESULT_INSERTED_ONCE` | integration | Result entered main-session history exactly once |

Race winners are deterministic: delete/pause/update before admission produce no
new occurrence; admission before mutation preserves its old snapshot; duplicate
admission replays the stored snapshot; active same-routine work skips without
backlog; resume fences every old paused candidate; and a replacement waits for
effective cancellation. CLD-013 must exercise both lock winners with PostgreSQL
barriers, not sleep-only or SQLite tests.

Idempotency is exact: same key and semantic fingerprint returns the original
receipt, while same key with changed identity/prompt/revision/occurrence/result
returns `IDEMPOTENCY_CONFLICT`. Expected revisions and Foundry generations fence
stale writes/events. Duplicate identical events are acknowledged; changed
replays and out-of-order stale generations are rejected without mutation.

## Privacy, retention, and compatibility

The saved prompt and evidence contain no credentials or tool grants. Existing
authorization, approval, payload, event, and same-conversation protections
remain in force. Full prompts are rejected before persistence if a boundary
cannot carry them; they are never truncated. Retention remains governed by the
existing policy inventory: do not delete an unacknowledged delivery, live
approval, execution evidence, or dedupe tombstone needed by a supported replay
window. No new quota or user-visible cadence restriction is invented here.

The fixture and tests intentionally prove only artifact bytes, hashes, canonical
fingerprints, and complete future-vector metadata. CLD-013/FND-012 own actual
authorization, schedule transitions, approval CAS, lease/binding changes,
result insertion, and PostgreSQL race enforcement. Contract compatibility does
not claim product readiness. Integrated release remains blocked until both
repositories support this tuple and real Class B evidence proves the required
session behavior.
