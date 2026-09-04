# FND-009 Wake on Intent Work Brief

## Outcome

Reduce the delay users feel when sending a message to an existing Ally whose shared Workspace Machine is stopped. The first meaningful composer edit should start the existing Machine early, while message submission remains the authoritative execution trigger and still succeeds when speculation fails.

## Accepted product and architecture baseline

- Foundry owns runtime lifecycle, readiness, Machine generations, executions, attempts, leases, ordered runtime events, and provider adapters.
- Cloud owns users, authorization, Workspaces, Allies, conversations, messages, rollout policy, and the browser-facing API.
- Interface talks only to Cloud. It never calls Foundry or Fly directly.
- One Fly Machine and one persistent volume are shared by all Allies in a Workspace. The Machine may stop only when every Ally on that Workspace is inactive: no queued or active execution, no unresolved lease, and no unexpired keep-warm window.
- The first release supports only `composing_started`. `conversation_opened` is explicitly deferred until false-wake cost is measured.
- Speculation only wakes an existing stopped Machine. It must not provision the first Machine, create executions or leases, open Hermes sessions, write conversation events, rotate credentials, create a replacement Machine, or start a second volume writer.
- Message submission is independent and authoritative. A missing, rejected, timed-out, or failed intent cannot block or delay send.
- Foundry may report `ready` only after the recorded Machine is started, the current generation has authenticated, startup profile reconciliation has completed, and a fresh readiness receipt identifies the current Machine generation and boot.
- Runtime intent payloads contain no draft text, conversation content, provider credentials, or user identity beyond the already-authorized resource path.

## Baseline commits and branches

- Foundry: `origin/dev` at `f689f0250561644d168e7ec799482ac1f1bced2e`; feature branch `ft/fnd-009-wake-on-intent`.
- Cloud: `origin/dev` at `2f4953dddc113ddf48e322267dc5998bcd0cfe10`; feature branch `ft/fnd-009-wake-on-intent`.
- Interface: PR #18 head `web/dev/figma-chat-ui` at `52390d0fad0d68505111c4f5251245f95db8da9d`; stacked feature branch `web/ft/fnd-009-wake-on-intent`.
- Existing unrelated worktrees and dirty changes are out of scope and must remain untouched.

## Required contracts

### Browser to Cloud

`POST /api/v1/allies/{ally_id}/runtime-intents`

- Existing browser authentication, membership authorization, and CSRF protections apply.
- Require `Idempotency-Key`.
- Strict JSON body: `{ "intent": "composing_started", "occurred_at": "<RFC3339 timestamp>" }`.
- Reject unknown fields, content fields, and unsupported intent types.
- A successful duplicate is replay-safe. The browser retries once with the same key after a transient failure.
- Rate limit: 20 runtime intents per authenticated user per minute.
- Workspace rollout policy: `off | composing | open`; default `off`. The first release implements behavior for `off` and `composing`; `open` is reserved and must not emit `conversation_opened` yet.
- A global kill switch disables forwarding without changing message submission.

### Cloud to Foundry

`POST /api/v1/control/workspaces/{workspace_id}/runtime-intents`

- Existing Cloud service authentication applies.
- Forward the same `Idempotency-Key`, the allowed intent type, and Cloud's server receipt time only.
- Do not forward Ally, user, conversation, draft, content, credential, or provider fields.

### Runtime to Foundry

`POST /api/v1/runtime/readiness`

- Authenticate with the current generation-scoped runtime bearer token.
- Strict body identifies a new boot UUID and the reconciled generation.
- Reject retired generations, mismatched generations, stale boots, and malformed receipts.
- A fresh valid receipt is the durable proof used by wake completion. Provider `started` state alone is not readiness.

## Foundry durable state and lifecycle

- Store idempotent runtime intents for ten minutes with Workspace, key, type, received/expiry timestamps, outcome, and the coalesced runtime operation. Intent eligibility expires after two minutes. Do not store content or user-facing identity.
- Track current readiness on the Workspace: ready generation, boot ID, ready timestamp, last runtime sighting, speculative keep-warm deadline, and last speculative start time.
- Concurrent intents for one Workspace coalesce onto one wake operation. At most one provider start is attempted for a stopped current-generation Machine.
- Allow at most one speculative provider start per Workspace per five minutes and at most 30 intents per Workspace per minute. These cost controls never restrict prompt-triggered starts.
- Return an explicit bounded outcome such as disabled, already ready, waking, ready, first provision required, or failed. Speculative failure is observable but never changes message admission semantics.
- A successful composing intent extends the Workspace keep-warm deadline. The production default is ten minutes and must be configurable in seconds so the local proof can use a short interval.
- Runtime readiness includes a bounded freshness heartbeat so a stale process cannot remain indefinitely ready.
- Add a bounded idle-stop command/process suitable for the existing Foundry event-publisher process topology. It must select only Workspaces whose keep-warm deadline has expired and whose queued/active work and unresolved leases are absent; it then stops the recorded current Machine through the existing provider boundary and rechecks under a lock before mutation.
- A later prompt submission must still wake/start a stopped Machine even when no composing intent arrived.

## Interface behavior

- Emit once per Ally conversation view on the first non-whitespace edit.
- Be IME/composition aware and React Strict Mode safe.
- Reuse the same idempotency key for one retry only.
- Never include draft text and never gate, disable, await, or delay message submission.
- Do not add a visible loading state for speculative wake. Existing send/activity states remain the user-facing truth.

## Local realism requirement

The final proof must use the Dockerized Foundry and Cloud topologies plus the local Interface server. Local commands must match Railway staging as closely as practical:

- Foundry web runs through the production Docker entrypoint/Gunicorn command, migrations run separately, and the event publisher runs as its own process.
- Cloud runs migrations, Gunicorn web, Celery worker, and Celery beat as separate Compose services using the same flags as Railway staging.
- PostgreSQL and Redis remain local. No staging database is used.
- Use a configurable short keep-warm/idle interval only for the local proof.
- Exercise an existing Workspace Machine through `stopped -> wake requested -> ready -> message response -> idle -> stopped`, then wake and respond again without a page refresh.
- Verify a second Ally on the same Workspace prevents Machine stop while it has queued/active work or an unresolved lease.
- Capture timestamps and durable/provider state for wake start, readiness, first streamed activity/token, completion, and stop. Do not claim a latency improvement without cold/warm comparison evidence.

## Acceptance criteria

1. First non-whitespace composer edit produces at most one privacy-safe `composing_started` intent per view and one same-key retry; message send remains independent.
2. Cloud enforces CSRF, authentication, Workspace/Ally membership, strict schema, idempotency, rollout policy, kill switch, and 20/user/minute limiting before a minimal Foundry call.
3. Foundry coalesces duplicate/concurrent intents and never creates speculative executions, attempts, leases, sessions, events, Machines, volumes, credentials, or replacement writers.
4. Existing stopped Machines wake; first-ever/unprovisioned Workspaces return a non-provisioning outcome.
5. `ready` requires a fresh current-generation/current-boot readiness receipt after startup reconciliation.
6. Idle stop occurs only after the shared Workspace has no queued/active work, no unresolved lease, and no keep-warm time remaining. Any active Ally prevents the shared Machine from stopping.
7. Prompt submission remains the authoritative fallback and starts a stopped Machine when the intent was absent or failed.
8. Unit and integration tests cover authorization, tenant isolation, strict validation, duplicate/reordered/concurrent delivery, stale generation/boot, provider timeout/failure, kill switch, policy off, IME/Strict Mode behavior, and idle-stop races.
9. The complete repository validation suites pass, followed by the Dockerized cross-repository end-to-end proof above.
10. No PR is opened until the local end-to-end proof passes. PRs are opened but not merged.

## Out of scope

- `conversation_opened` speculation and its 750 ms dwell experiment.
- First-ever speculative provisioning.
- Per-Ally Machines or per-Ally idle timers.
- Disabling SSE, changing message semantics, or adding a new queue solely for runtime intents.
- Railway/staging mutation, production rollout, or PR merge. A bounded local-control-plane smoke may mutate only exact, preflighted proof-owned Fly resources and must restore or remove them by recorded ID.
