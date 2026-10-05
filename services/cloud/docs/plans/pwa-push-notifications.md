# PWA push notifications plan

Route: fast. HTML required: no. Scope accepted on 2026-09-29; implementation and two PRs into `dev` are authorized without another owner approval. Merge, production deployment and native push remain outside this episode.

## Feature Overview

Opted-in web/PWA users receive approval-needed, routine completed/failed/attention and completed ordinary-reply notifications while this subscribed browser is hidden or closed. Taps open the owning Ally's main conversation. Conversation history and authenticated approval APIs remain authoritative.

Existing web has a manifest and installation UI but no service worker. Cloud already persists assistant replies, pending approvals and routine result projections, and runs Celery worker/beat. Add a narrow `notifications` domain using those transitions; do not change Foundry, replay routines, add a standalone service, or build a general channel framework.

## Scope and evidence

- Canonical Nabu notes inspected: `projects/allies/index.md`; `engineering/specs/pwa-push-notifications.md` (accepted scope); `engineering/specs/routines.md`; `engineering/specs/conversation-and-streaming.md`; `engineering/guides/foundry-cloud-boundary.md`. Older routine notes defer push; the new owner instruction and accepted push note explicitly add this release without changing approval authority or run semantics.
- Both worktree `AGENTS.md`, `ENGINEERING_STYLE.md`, README and CI; Cloud Makefile, `backend/pyproject.toml`, `docs/templates/PLAN_TEMPLATE.md`, `docs/plans/kickoff.yaml`; Interface parent napkin, `apps/web/AGENTS.md`, root/web package scripts and Vitest configuration. Fast route overrides the older napkin's full-template convention. Worker selectors are `sol_planning_worker`, `sol_review_worker`, `sol_execution_worker`.
- Cloud: `backend/activities/services/projection.py` (`_apply_foundry_event`, `_rich_approval_for_event`), `backend/chat/services/messages.py` (`complete_turn`), `backend/routines/services/results.py` (`project_routine_result`, `_complete_routine_result_insertion_locked`), `backend/routines/services/approvals.py` (`apply_routine_approval_requested_event`), `backend/auths/services/sessions.py` (`logout_session`, `revoke_family`), `backend/config/{api,celery,settings}.py` and auth success/error envelopes.
- Web: `apps/web/lib/session/web-session.ts`, `session-context.tsx`, `apps/web/app/{providers,account/account-client}.tsx`, `apps/web/lib/pwa/pwa-install.tsx`, manifest, Next config, Home conversation/approval components, `packages/cloud-client/src/{client,transport,schemas}.ts`, schema snapshot and `scripts/fetch-cloud-openapi.ts`. Root's Pencil inspection found existing DSN-006 Settings `W8JNz` Notifications switch; Notes `fHt4G` calls for one global account switch now, using orange DS-Toggle `NHv2c` (44x26, 20px knob). Reuse that row; Pencil owns design.
- Installed Next PWA guide: `node_modules/next/dist/docs/01-app/02-guides/progressive-web-apps.md`. Use its native worker/static asset approach, retaining Cloud as the backend. [pywebpush producer documentation](https://github.com/web-push-libs/pywebpush) inspected 2026-09-29: it supplies encryption/VAPID and bounded request timeout; choose a locked compatible release and inspect its transport before integrating. Its upstream notes single-maintainer risk.

## Contract and Shape Definitions

Cloud owns this additive `/api/v1` contract and publishes OpenAPI. Web owns the native worker protocol. Snake-case JSON is identical in Python schemas and TypeScript/Zod; UUIDs are canonical strings, timestamps are UTC ISO 8601 with timezone, integers are strict. Reject unknown request fields. No owner ID is accepted from a client; derive owner and session family from browser authentication.

```ts
type UUID = string;
type UTC = string;
type Envelope<T> = { status: "success"; message: string; data: T };
type PushConfig = {
  enabled: boolean; vapid_public_key: string | null;
  presence_ttl_seconds: 60; heartbeat_seconds: 20;
};
type RegisterPush = {
  browser_id: UUID; binding_id: UUID;
  replaces_binding_id: UUID | null;
  endpoint: string; keys: { p256dh: string; auth: string };
};
type PushRegistration = {
  subscription_id: UUID; browser_id: UUID; binding_id: UUID;
  workspace_id: UUID; session_id: UUID; state: "active";
};
type PushPresence = {
  binding_id: UUID; client_id: UUID; sequence: number; visible: boolean;
};
type PresenceReceipt = { accepted_sequence: number; foreground_until: UTC | null };
type RevokePush = { binding_id: UUID };
type PushPayload = {
  version: 1; notification_id: UUID; binding_id: UUID;
  kind: "approval_needed" | "routine_completed" | "routine_failed"
      | "reply_completed";
  workspace_id: UUID; ally_id: UUID; conversation_id: UUID;
  expires_at: UTC;
};
```

All routes below use prefix `/api/v1/workspaces/{workspace_id}/push`. Require the existing authenticated **browser** session plus workspace membership; mutations additionally require trusted origin and CSRF through the existing Cloud transport. Native credentials are not accepted by these PWA-only routes. Resource lookups bind owner, workspace and current session family; unknown/foreign resources return the same 404. Session rotation within the family preserves subscriptions; a new family requires an explicit new binding.

| Method/path | Request | Success | Errors and repeat behavior |
| --- | --- | --- | --- |
| GET `/config` | none | 200 `Envelope<PushConfig>` | 401/403; no-store. Disabled or missing VAPID returns enabled false/key null without breaking account settings. |
| POST `/subscriptions` | `RegisterPush` | 200 `Envelope<PushRegistration>` | 401/403/409/422/429/503. `binding_id` is immutable idempotency identity: same bytes/current family returns same result; conflicting bytes or a revoked binding returns 409 `push_binding_conflict`. Disabled config: 503 `push_unavailable`. |
| POST `/subscriptions/{subscription_id}/presence` | `PushPresence` | 200 `Envelope<PresenceReceipt>` | 401/403/404/409/422/429. Current binding required; lower/equal sequence never overwrites newer state and returns current accepted sequence. |
| DELETE `/subscriptions/{subscription_id}` | `RevokePush` | 204, no body | 401/403/404/409/422. Same owner/workspace/family/binding repeated revocation remains 204; mismatched binding is 409. |

Representative JSON (UUID aliases below stand for canonical UUID strings in fixtures): registration `{"browser_id":"B","binding_id":"G","replaces_binding_id":null,"endpoint":"https://fcm.googleapis.com/...","keys":{"p256dh":"<base64url public key>","auth":"<base64url secret>"}}` returns `{"status":"success","message":"Push enabled","data":{"subscription_id":"S","browser_id":"B","binding_id":"G","workspace_id":"W","session_id":"F","state":"active"}}`. `session_id` is the authenticated session-family UUID already exposed by account `session.id`, derived by Cloud rather than accepted in registration input; it is an identifier, never an auth token. Config data is `{"enabled":true,"vapid_public_key":"<base64url public key>","presence_ttl_seconds":60,"heartbeat_seconds":20}`. Presence `{"binding_id":"G","client_id":"T","sequence":1,"visible":true}` returns envelope data `{"accepted_sequence":1,"foreground_until":"2026-09-29T14:01:00Z"}`. Revocation body is `{"binding_id":"G"}`. Standard existing error envelope/code handling applies; never echo endpoint/key input.

Registration JSON limit 8 KiB; endpoint at most 2048 characters; strict unpadded base64url keys decoding to a valid 65-byte uncompressed P-256 point and a 16-byte auth secret. Presence sequence 1..2^31-1 and client ID unique per tab lifetime. At most five active subscriptions per owner/workspace and eight live presence entries per subscription. Preserve expired entries' sequence high-water marks for binding lifetime, capped at 256 distinct tab IDs; reject new IDs with 429 at that cap instead of forgetting newer sequences. Renewal creates a fresh bounded ledger. Foreground TTL expiry removes visibility authority, never ordering history. Reuse `auths.throttle.check_rate_limit`: register/revoke 20/minute per owner, presence 6/minute per tab and 60/minute per subscription. A browser binding covers one workspace; workspace changes clear/revoke/rebind rather than sharing an endpoint across scopes.

### Subscription, state and privacy invariants

- `PushSubscription`: UUID, owner/workspace/session-family FK, browser UUID, unique binding UUID, endpoint digest (unique among active records), encrypted endpoint/key blob using inspected `backend/common/vault.py` `seal_secret`/`unseal_secret` and existing `ALLIES_VAULT_KEYS`, active/revoked state, timestamps and bounded presence map. Never log endpoint capabilities, keys, payloads, provider bodies or exception representations. VAPID secrets are deployment prerequisites, not committed values; no new storage-encryption key setting.
- A new registration replaces only `replaces_binding_id`, which must equal this owner/browser's currently active binding under the Cloud lock; null requires no current active binding. Check same-UUID idempotent replay first. A mismatch returns 409 without retiring anything, so concurrent renewals cannot retire the winning binding and leave its UI falsely enabled. Never silently transfer an active endpoint from a different owner/session; return 409. Account replacement unsubscribes locally before creating the new native subscription. Failure to obtain a fresh safe binding leaves push disabled with recovery copy.
- Subscription renewal always creates a **new binding UUID** when endpoint or keys change, then atomically retires the prior same-owner/browser binding on Cloud. Authenticate registration before activating the new worker binding. Persist the pending new UUID and exact registration bytes before sending; a lost response retries those same bytes/UUID and returns the original registration, never a second renewal. If the worker receives `pushsubscriptionchange` without an authenticated open client, mark `renewal_needed:true`, clear its old active binding and defer Cloud registration until the next authenticated opening. Renewal follows prior explicit consent without another permission prompt; failure leaves Notifications in recovery/off state until authenticated retry succeeds.
- Revocation leaves a binding tombstone so an in-flight registration cannot reactivate it. Retain tombstones until the originating session family expires; delete only when no valid request for that family can arrive. Owner session-family revocation/expiry makes every associated subscription immediately ineligible at send time; integrate central logout cleanup as needed. Do not tie eligibility to the short access-token expiry.
- `PushNotification`: UUID, unique stable product identity, kind, owner/workspace/Ally/conversation ancestry, optional source approval/reply/result FK and expiry. Only references/metadata, never preview text. `PushDelivery`: subscription FK + notification FK unique pair, binding snapshot, pending/sending/sent/suppressed/retired/failed state, bounded attempt count, next attempt, lease and safe error code. These three tables are a small delivery outbox, not runtime leases.
- Persist notification intent in the **same database transaction** as the durable product transition. `on_commit` only nudges Celery; a beat recovery scan finds pending work if queue publish fails. Capture eligible subscription IDs at event creation, so enabling later never sends old replies. No historical backfill.

### Eligibility and delivery

| Product transition | Stable identity and eligibility |
| --- | --- |
| Ordinary `execution.awaiting_action` rich approval and routine approval projection | `approval:<authoritative request UUID>`; only exact pending, not decision-recorded/terminal/expired, with matching owner and active Ally/conversation. If both projection paths observe the same approval request, dedupe once. |
| `execution.completed` after `AssistantReply` persistence in `_apply_foundry_event` | `reply:<AssistantReply UUID>`; non-empty durable reply, ordinary main-conversation user send. Exclude routine execution/result origins, onboarding/system work, failed/stopped turns and every delta/activity event. `complete_turn` alone is not sufficient evidence of a reply. |
| Routine result's first `INSERTED` transition in `_complete_routine_result_insertion_locked` | `routine-result:<RoutineResultProjection UUID>`; changed/unchanged map to `routine_completed`, failed to `routine_failed`. Existing result enum has no attention outcome: routine attention currently comes from the exact pending routine approval above, as `approval_needed`; do not invent a runtime event. Notify only after durable main-conversation insertion, not receipt of a still-held result. No second normal-reply notification. |

Expire reply intents after one hour, routine outcomes after 24 hours, approvals at their authoritative expiry (maximum 24 hours). Reconcile exact approval/run status and owner membership before **each** provider attempt. Push cannot approve anything; stale taps load current in-app state and reveal no decision controls for terminal requests.

Before dispatch, compare unexpired visible presence's server-received timestamp with the notification creation timestamp. A strictly newer visible heartbeat confirms foreground for this event: mark suppressed terminal, with no later replay. Presence recorded before or at event creation is only cached evidence: keep delivery pending and defer to its expiry, without consuming a transport attempt, rather than permanently suppressing. If the app closes/crashes without a hidden update, it therefore receives the event after stale presence expires (next 60-second beat scan, at most roughly 120 seconds from its last visible heartbeat). A newer hidden update can release the deferral sooner; a newer visible heartbeat can confirm suppression. Store these timestamps in the existing bounded presence map; rejected duplicate/stale sequence updates never refresh them. Presence TTL is 60 seconds, visible heartbeat 20 seconds, immediate hidden/pagehide update best effort. These are fixed v1 protocol intervals, not independent runtime configuration. A hidden tab never clears another visible tab's entry. SSE connectivity is not presence. Do not send silent pushes to discover foreground state.

Accepted engineering assumption for review: [WebKit requires received pushes to display notifications](https://webkit.org/blog/16535/meet-declarative-web-push/), so unconditional receipt-time `clients.matchAll` suppression can revoke permission. Use backend suppression before send, then display valid already-accepted pushes even if the app became foreground in transit. Root accepts this bounded in-flight race; absolute foreground suppression is not claimed. Fail-closed owner/expiry checks still take priority, with exceptional silent drops potentially requiring resubscription. This adds no owner approval gate.

Use the existing `cloud` Celery queue: beat scan every 60 seconds, at most 50 due deliveries per invocation, one provider call per delivery attempt, 10-second HTTP timeout, 30-second delivery lease, bounded task time. Provider 2xx means accepted, not device-shown. Retire on 404/410; retry network timeout, 408, 429 and 5xx at most three total attempts with 30/120-second backoff (Retry-After clamped to 300 seconds), bounded by event expiry. Other 4xx fail terminal; 401/403 emit a safe configuration-error count. Recover expired sending leases; provider acceptance followed by a worker crash may cause a duplicate, handled by the unchanged notification ID at the worker. Do not claim exactly-once delivery across provider failures.

SSRF boundary: HTTPS only, port absent/443, no userinfo/fragment/IP literal, parsed exact ASCII host allowlist initially `fcm.googleapis.com`, `updates.push.services.mozilla.com`, `web.push.apple.com`; no user-provided host patterns or suffix match. Validate all resolved addresses are public at registration and each attempt. Reject redirects and environment proxies; use a controlled HTTP session/transport with no redirect following and bounded response reading. Inspect the pinned pywebpush transport and override its request session if needed; do not assume its defaults meet these controls. Because destinations are fixed provider-controlled hosts, clients cannot choose rebinding hosts. Provider changes require reviewed allowlist additions; unsupported endpoints fail clearly instead of broadening the boundary.

Payload is the typed `PushPayload`, UTF-8 <=1 KiB, no arbitrary title/body/URL or approval action buttons. Worker renders title `Allies` and fixed copy by kind: `An approval needs your attention.`, `A routine completed.`, `A routine failed.`, `Your Ally has replied.`. Provider TTL is min(300 seconds, remaining event lifetime). This limits transport staleness but an already displayed OS notification cannot be reliably recalled on another device's decision; in-app authoritative revalidation is mandatory.

## Web lifecycle and navigation

Register `apps/web/public/sw.js` with root scope and no offline fetch caching; configure no-cache worker response headers. Settings Preferences reuses existing controls for Notifications: unsupported, off, enabling, enabled, disabling and failed/retry states; denied permission explains browser settings, iOS unsupported/noninstalled explains installation. Request permission only from explicit user gesture. Do not auto-prompt on login or persist enabled success before both native and Cloud registration succeed.

Worker IndexedDB stores `{browser_id,epoch,binding,renewal_needed,pending_registration}`: `epoch` is a monotonically increasing nonnegative safe integer, `binding` is the active binding record or null, and pending registration is nullable exact `RegisterPush` bytes plus the epoch observed before registration. It also stores a capped dedupe set (latest 256 notification IDs, 24-hour expiry). Persist active binding only after registration succeeds. The persistent worker epoch is the cross-tab/restart authority; existing session-provider generations remain an additional local guard, never its replacement. Cross-tab broadcast informs other tabs of changed epoch/state but is not required for fencing correctness.

Before logout begins, capture the account's owner/session-family IDs, cancel that tab's enable/renewal operations, send the worker a clear using its captured epoch, and await ACK before best-effort revoke/unsubscribe and server logout. If clear rejects because a bind advanced the epoch first, reread `PUSH_STATE` and retry clear at most three total attempts **only** while the active binding belongs to that captured owner/session family (or no binding exists). Never clear a newer account or a new session family, even for the same owner. Each attempt passes the captured logout scope below; the worker checks scope as well as epoch atomically. Successful clear advances epoch even with null binding, fencing pending old operations. Exhaustion/timeouts mean unconfirmed cleanup, not success; keep local UI disabled, revoke the captured server family, and retry cleanup later without touching a replacement family. Unauthorized restore/account changes use the captured prior session scope; explicit disable and workspace replacement retain exact-binding clearing, so a stale toggle operation cannot disable a newer enable. Failed remote revocation never restores enabled state. Invalid/unknown binding, malformed/expired payload or missing IndexedDB safely drops the event. Never carry session tokens in worker messages or storage. A revoked binding requires a new explicit enable gesture and UUID; changed material follows renewal above.

Worker messages use exact envelopes over a MessageChannel:

```ts
type WorkerBinding = PushRegistration & { owner_user_id: UUID; enabled: true };
type PendingRegistration = {
  expected_epoch: number; owner_user_id: UUID; session_id: UUID; workspace_id: UUID;
  registration: RegisterPush;
};
type CleanupRecord = {
  cleanup_id: UUID; owner_user_id: UUID; session_id: UUID; workspace_id: UUID;
  binding: WorkerBinding | null; pending_registration: PendingRegistration | null;
};
type WorkerRequest =
  | { type: "PUSH_STATE" }
  | { type: "PUSH_SUBSCRIBE"; expected_epoch: number; vapid_public_key: string }
  | { type: "PUSH_CLEANED"; expected_epoch: number; cleanup_id: UUID;
      rotate_browser_id?: boolean }
  | { type: "PUSH_PREPARE"; expected_epoch: number; owner_user_id: UUID;
      session_id: UUID; workspace_id: UUID; registration: RegisterPush }
  | { type: "PUSH_BIND"; expected_epoch: number; binding: WorkerBinding }
  | { type: "PUSH_CLEAR"; expected_epoch: number; binding_id: UUID | null;
      expected_pending_binding_id: UUID | null;
      logout_scope: { owner_user_id: UUID; session_id: UUID } | null };
type WorkerReply =
  | { type: "PUSH_SUBSCRIPTION"; accepted: boolean;
      subscription: { endpoint: string; keys: { p256dh: string; auth: string } } | null }
  | { type: "PUSH_STATE"; browser_id: UUID; epoch: number;
      binding: WorkerBinding | null; renewal_needed: boolean;
      pending_registration: PendingRegistration | null;
      renewal_binding: WorkerBinding | null; material_fingerprint: string | null;
      cleanup_record: CleanupRecord | null }
  | { type: "PUSH_ACK"; accepted: boolean; epoch: number; binding_id: UUID | null; enabled: boolean };
```

`PUSH_PREPARE` uses the same source validation and epoch CAS to persist exact scoped registration bytes before the authenticated Cloud request, without advancing the epoch. It is first-writer-wins: accept an empty slot or identical replay, reject different pending bytes/scope until explicit reconciliation or clear. An accepted clear erases pending registration; bind must match its identity and owner/session/workspace scope when present. Recover pending requests only after a fresh authenticated owner/session/workspace check. This small persistence message supports lost-response recovery; it grants no authentication authority.

Clear additionally compares `expected_pending_binding_id` (including null) with the current pending registration atomically. This fences a stale clear when preparation changed at the same epoch after its state read. Scoped logout reconciliation rereads this identity on each bounded retry, and never clears pending work from a replacement owner/session. Test prepare-after-read versus stale-clear rejection.

Before disarming state, clear captures known binding/renewal identity and exact pending registration in one inactive `cleanup_record`; an empty clear preserves existing cleanup. It cannot admit notifications or supply consent. Fresh authenticated matching owner/session recovery reconciles exact pending POST idempotently, then revokes the resulting/known subscriptions. Workspace changes revoke through the captured old workspace before enabling in the new one. Do not prepare new enablement while cleanup remains unresolved. `PUSH_CLEANED` erases only the matching cleanup ID/current epoch without advancing epoch. Foreign owner/session cleanup never invokes old credentials or clears a replacement binding. Tests cover failed revoke, lost registration response, workspace changes and stale cleanup completion.

Lifecycle recovery verifies current authenticated owner/session/workspace before acting on cached account state. Background recovery never clears a foreign owner/session binding. Only an explicit enable gesture may replace it: capture worker state first, verify current authentication, perform the exact captured-scope/epoch clear, verify authentication again and CAS-consume the captured cleanup record. `PUSH_CLEANED` with `rotate_browser_id:true` creates a fresh logical browser UUID and advances epoch for this foreign-account/session handoff; ordinary same-family cleanup does not advance epoch. This prevents old Cloud browser/family records blocking the new account without old credentials. Reject stale CAS rather than replaying with a new epoch. Every disable/recover continuation checks captured generation/account/registration after awaits before mutation. Worker activation waits are bounded to the existing operation timeout and expose retry. Expose typed logout notification-cleanup confirmation separately from server logout; retain only validated captured owner/session identifiers for bounded signed-out/startup cleanup retry, preserving replacement accounts and allowing normal logout to complete. Delayed logout never erases foreign cleanup records or a newer persisted cleanup intent; signed-out retries continue reporting unconfirmed state until the captured cleanup succeeds.

On successful bind retain a SHA-256 `material_fingerprint` of the endpoint and keys in a fixed serialization, then discard pending bytes. Compare it with current native subscription material during authenticated opening so unchanged subscriptions do not renew on every opening. Clear erases the fingerprint. No extra retained full endpoint/key record is needed.

Closed-worker subscription change preserves `renewal_binding` as inactive old-binding metadata solely to supply replacement identity after clearing the active binding and advancing epoch. It never admits displays or clicks. Clear erases it; recovery requires a fresh authenticated owner/session/workspace match and the current epoch.

The worker queue also owns native subscription mutations. After synchronous window-side permission request, `PUSH_SUBSCRIBE` checks the captured epoch before getting/creating the native subscription with the validated VAPID public key. A stale request rejects without native mutation. Clear persists its fence, closes old notifications and completes best-effort native unsubscribe before ACK, so replacement enables cannot race an old unsubscribe. Window code may read native state but never subscribe/unsubscribe. Subscription-change handling uses the same queue. Validate lifecycle generation/account after each await before further mutation or publishing enabled state.

Read `PUSH_STATE` **before** starting authenticated registration; carry that expected epoch through its response and `PUSH_BIND`. Bind and clear perform IndexedDB compare-and-swap: accept only current `expected_epoch`, and clear requires the expected binding ID (including null); if `logout_scope` is present, a nonnull active binding must additionally match both captured owner and session IDs. Accepted mutations advance epoch and persist before ACK. A mismatch returns `accepted:false` without mutation. A rejected bind must not automatically reread the epoch and replay stale credentials/registration; discard that operation and recover only from a fresh authenticated account check and lifecycle intent. Only scoped logout clear has the bounded reread/retry exception above. Validate source is a same-origin app WindowClient and only the current account/session operation may accept ACKs. Persistent CAS rejects delayed old-tab binds across broadcast loss and worker restart, while scoped reconciliation handles bind winning immediately before logout clear.

Use one worker-local promise queue to serialize bind, clear, push display and click admission; keep each queued operation alive with `event.waitUntil`. Push rechecks persisted binding/epoch in this queue and awaits `showNotification`; clear waits for all previously admitted displays, advances the persistent fence and awaits closure of old-binding notifications before sending ACK. Therefore no previously admitted display can complete after a successful clear ACK. On worker startup/restart reconcile `getNotifications()` against the persisted binding, closing stale ones before admitting displays/clicks. Notification `data` includes binding ID for reconciliation; use tag `allies:<notification_id>`, `renotify:false`, and dedupe persist-before-display. A display failure may drop one alert; conversation history remains available. No push receipt invokes private Cloud reads or stores auth credentials. If clear ACK fails/times out, still complete normal logout, keep local push disabled, and retry worker cleanup; do not report successful notification cleanup.

Clicks derive only `/home/<canonical ally UUID>` from payload; never trust an external route. Verify worker binding again, focus/navigate an existing same-origin app window or open that path. The existing authenticated Home flow checks workspace/Ally access and resolves the owning main conversation; validate expected conversation/workspace before rendering. Signed-out navigation uses existing sign-in return handling. No push route executes a decision, opens a private routine-run conversation, or bypasses current authorization.

Implementation inspection found current sign-in resets navigation to `/home`. Add narrow return handling through landing/onboarding for validated same-origin `/home/<canonical Ally UUID>` with optional canonical push workspace/conversation parameters. Reject arbitrary or foreign destinations; test signed-out notification target recovery after sign-in.

## Implementation Phases and worker lanes

1. **Cloud lane (`sol_execution_worker`)**: additive notifications domain/models/migrations/API, locked pywebpush dependency and controlled provider transport; config/API registration and Celery schedule; same-transaction hooks in activity, routine approval and result projections; central session-family fencing. Add focused authorization, event eligibility, concurrency and transport tests. Publish a local OpenAPI export after the Cloud commit and provide its exact revision/path to integration.
2. **Web lane (`sol_execution_worker`, independently in Interface)**: start against the exact contract above with fixtures. Add push adapter to `packages/cloud-client`, worker and lifecycle helper under `apps/web/lib/pwa`, Preferences control, provider/session cleanup integration, worker headers and tests. Do not edit mobile UI. Reuse native APIs and existing session/transport, not a PWA plugin or separate push SDK.
3. **Integration/orchestrator**: update the Interface committed OpenAPI snapshot/metadata from the Cloud export using `ALLIES_CLOUD_OPENAPI_FILE` plus the actual 40-character `ALLIES_CLOUD_OPENAPI_REVISION`, `bun run cloud:fetch`, then `bun run cloud:generate`. Never edit generated schema manually or label uncommitted schema as a committed revision. Reconcile schema/fixture differences through this plan before accepting either lane.
4. **Validation and independent reviews**: run focused checks, then relevant full checks; separate adversarial/simplicity plan reviews and correctness/simplicity code reviews. Required policy/security and tenant controls remain. Document real-device/release prerequisites and open two linked PRs into dev. No deployment or merge.

Two coherent PRs, one per repository, keep backend migrations, tests and hooks together and worker/lifecycle/navigation tests with the web change. Exclude unrelated refactors. If a PR exceeds 500 non-generated changed lines, actively consider splitting only independently testable work; never split safety checks away from behavior. Cloud merges/releases before compatible web enablement.

## Acceptance Criteria and validation

- Backend focused checks: `make test APP=notifications/tests`, `make test APP=activities/tests`, `make test APP=routines/tests`, `make test APP=auths/tests/test_sessions.py`. Cover foreign owner/workspace/family, CSRF/origin, session expiry/revoke, exact endpoint allowlist and DNS/private addresses/redirects/proxy behavior, key/size/rate limits, repeated revoked binding registration, duplicate event races, routine/reply exclusion, held results, stale approvals, foreground multi-tab sequence/expiry, retry exhaustion, dead endpoints and post-acceptance worker crash. Test a cached pre-event visible heartbeat followed by closed/crashed app with no hidden update: delivery remains pending and sends after TTL; a newer post-event visible heartbeat instead suppresses it.
- Cloud complete relevant checks: `make check`, `make lint`; backend `uv lock --check`, `uv run ruff format --check .`, `uv run pytest`, `uv run pytest --cov=auths --cov=workspaces --cov-fail-under=90`, fresh migration application/check and PostgreSQL `uv run pytest -m postgresql`. Concurrency tests must exercise same-event and same-binding claims on PostgreSQL. Local Docker/PostgreSQL is unavailable: these concurrency and PostgreSQL migration checks are required in the existing hosted CI PostgreSQL job; do not claim they ran locally. No external credentials needed for deterministic fake provider tests.
- Web Vitest through `bun run test:run -- --project web` and package push adapter tests; verify permission denied/unsupported, revoke failure, renewal with changed endpoint/keys and lost-response same-UUID recovery, closed-worker renewal deferral, stale enable completion after logout, delayed old-tab binds after a clear and worker restart, and a paused `showNotification` raced with logout (clear ACK waits for display completion and closure). Deterministically let bind win and increment epoch before queued logout clear: first clear rejects, reread/scoped retry clears the logging-out family's binding; a replacement account or same-owner/new-family binding survives unchanged. Also cover retry exhaustion, two-tab account replacement, malformed binding/payload, expiry/dedupe, backend-presence foreground suppression and same-origin click navigation/auth denial. Exercise the real static worker with a lightweight VM/browser harness, not a second mock implementation.
- Interface completion: `bun run cloud:check`, `bun run typecheck`, `bun run test:run`, `bun run lint`, `bun run build:web`; shared package/schema changes also require CI-selected mobile compatibility/export (`bun run bundle:mobile`) though native push is unchanged. Use pinned Bun 1.2.20 (host 1.3.14 differs; invoke `npx -y bun@1.2.20` if necessary). Playwright runs with explicit `apps/web/playwright.config.ts`; test grant/deny control, worker registration and safe route opening using controlled push events. Mock/browser tests do not prove installed-device delivery.
- Before production acceptance: opt-in hidden/closed/foreground delivery and click smoke on installed iOS Safari PWA, Android Chromium and desktop browser; test a decision made on another device and account/logout changes. Record device/OS/browser and whether actual provider delivery ran. PR readiness may state these remain pending, never claim production acceptance from fixtures.
- Worker recovery checks also race two different prepares at the same epoch: only the first can reserve pending bytes, exact replay succeeds, and competing bytes cannot erase recovery identity. Workspace changes cannot recover or bind a pending registration from the old scope. Unchanged native material must not cause repeat renewal on app opening.
- Pause native unsubscribe inside clear and race a replacement subscribe: clear ACK waits, the stale captured-epoch subscribe rejects, and a fresh replacement subscription survives. Logout while native read/fingerprint is pending cannot restore enabled UI or presence.

## Risks, rollout and rollback

No unresolved product decision. Engineering assumptions: fixed generic copy, all three categories enabled together per browser/workspace, five active subscriptions, 60-second presence TTL, three transport attempts and fail-closed local fencing. Independent review may tighten limits without changing product scope. Verify real browser endpoints against the initial allowlist before claiming platform support.

Bound cleanup: beat deletes expired completed notification/delivery rows after seven days in batches of 100; active subscription endpoints retire with session family invalidation and private blob is erased; tombstones retain only binding/owner/session identity until family expiry. Dedupe records cover event lifetime. A post-event visible heartbeat can confirm suppression just before a crash; cached pre-event presence only delays delivery. OS delivery is best effort. No replay of confirmed-suppressed alerts or routine execution retry is introduced.

Rollout prerequisites: additive DB migrations, HTTPS, VAPID public/private pair and contact configured in secret store, working existing `ALLIES_VAULT_KEYS`, compatible Cloud worker/beat/backend and web worker, and recorded device smoke. Feature availability defaults on with an operational off switch; missing/invalid key configuration returns unavailable (`enabled:false`) and is nonfatal to normal chat. Actual consent/subscriptions still default off. Private keys never reach web bundles. Preserve public-key stability across redeploys; rotation requires resubscription.

Rollback disables push on Cloud first, stops new deliveries and hides the enable action; web clears/revokes active binding when disabled config is observed. Already accepted in-flight payloads may still arrive and local expiry/binding checks apply. Retain additive tables and conversation state; do not roll back migrations destructively. Existing installed workers cannot be instantly recalled, so payload v1 and safe click handling remain compatible while deploying a worker update.
