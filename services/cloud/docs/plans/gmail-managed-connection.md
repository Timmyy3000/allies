# Managed Gmail Connection (Generic Credential Passthrough, Gmail First) Plan

_HTML required: yes — user requested Lavish review session 2026-09-22; this Markdown is the source of truth._

## Feature Overview

- Problem: Allies users cannot give an Ally access to Gmail without creating their own Google Console project, pasting App Passwords, or handing long-lived secrets to every execution. The current Hermes paths are self-managed only: `google-workspace` skill expects a user-owned OAuth client (`skills/productivity/google-workspace/SKILL.md:82-115`) and `himalaya` expects password auth (`skills/email/himalaya/SKILL.md:30-35`), with a known Gmail duplicate-send landmine on folder-alias misconfiguration (`skills/email/himalaya/SKILL.md:91-100`).
- Target users: Allies end users connecting one Gmail account and granting per-Ally read/send; Ally operators revoking grants or disconnecting the account.
- Source docs/specs: `helpers/BOUNDARY.md` (placement law + 6 ticket tests); `allies-cloud/docs/architecture/cloud-domain-map-and-contract.md` (ownership, envelopes, 16 KiB cap, states); episode-state decisions D1–D11; evidence index paths cited inline below.
- Success outcome: v1 managed Gmail read + send over a provider-neutral credential-passthrough architecture — account-level Allies-owned OAuth (minimal scopes), per-Ally grants enforced in the Cloud gateway, short-lived ACCESS-only injection per execution, unmodified Hermes skill, approval-gated send, two-level revocation — passing BOUNDARY ticket tests 1–6 and pinning its 3 watchpoints, with Calendar explicitly reserved for a later incremental-consent increment.

## User Stories

1. As a user, I want to connect my Gmail once (Integrations page or in-chat) via Allies-owned Google OAuth granting only `gmail.modify` + `gmail.send`, so that my Allies can read and send mail without me running a Console project.
2. As a user, I want to grant one Ally read-only and another Ally read+send, and revoke either grant, so that a compromised or noisy Ally loses mailbox access without disconnecting my account (in-flight work is fenced, not silently continued).
3. As a user, I want every Ally-composed send/reply shown to me as a draft for approval before dispatch, so that nothing leaves my mailbox on an agent's authority alone.
4. As an operator, I want account disconnect to delete the vault refresh token, revoke at Google, and scrub materialized profile files, so that no execution can use the credential afterwards and I can prove it.

## Scope

### In Scope

- Allies-owned Google OAuth for Gmail v1 with minimal scopes `gmail.modify` + `gmail.send` (D8); entry points: Integrations page AND in-chat initiation with inline OAuth sheet and auto-grant to the requesting Ally (Req 1).
- Account-level connection + per-Ally grants (`read` vs `send`, explicit, revocable) enforced in the Cloud gateway before Foundry dispatch AND at each Gmail API call inside the execution (Req 2, ADV-001, SIM-001): dispatch holds the whole conversation command (not later skill args, which arrive via `google_api.py:318-420`) and the token carries both scopes — so the pre-dispatch check reads the live grant row and emits the execution's allowed-operation list (level→allowlist, no `requested_tool` input), and at the actual call boundary ONE provider-neutral gate checks that list + current grant generation + (on sends) the approval bound to the exact payload. A read-only or ungranted execution cannot reach send through any tool path.
- Generic credential passthrough: Cloud mints short-lived ACCESS-only tokens per execution; refresh + revoke + audit stay in Cloud; Foundry/runtime injects opaque bytes at the Hermes profile boundary; kernel never parses OAuth or names the provider; reuse `credential_refs` → profile `.env` machinery (`allies-foundry/runtime/allies_runtime/profile_store.py:1536-1537,1605`) (Req 3).
- Hermes `google-workspace` skill used UNMODIFIED; injected file carries no `refresh_token` so `get_credentials()` auto-refresh + write-back (`scripts/google_api.py:181-200`) never fires; expiry exits non-zero and maps to existing `retryable`/`repair_required` + reason code, no new event kind (D7, Req 4).
- Send/reply through the existing approval mirror (draft shown before dispatch) (Req 5).
- Two-level revocation: per-Ally grant delete (fence in-flight via generation) and account disconnect (Cloud deletes refresh, revokes at Google, requeues materialization to scrub profile files) (Req 6).
- Generic contract (opaque bytes + expiry + tool allowlist) so Twitter/Notion/Slack later cost zero Foundry changes; one generic encrypted tenant-scoped secret row in Cloud, not per-provider vaults; Calendar reserved, out of v1 (Req 7).
- BOUNDARY ticket tests 1–6 pass + 3 watchpoints pinned (Req 8).

### Out of Scope

- Google Calendar (explicitly reserved; follows later via incremental OAuth scopes — no calendar scope request, no calendar tool enablement in v1).
- Email-arrival triggers / routine scheduling on mail (Nabu `routines.md`: routines stay schedule-only).
- Himalaya as the managed default (D5: password auth, no consent/scopes/calendar; generic-IMAP fallback only, not built in v1).
- New Foundry event kinds, per-provider vaults, Cloud-held attempt/session state, kernel-side scope parsing.
- Speculative scale (multi-account fan-out, background sync workers, token-caching services beyond per-execution minting).

### Dependencies and Assumptions

- Allies-owned Google OAuth client (verified Desktop/Web client + consent screen) exists before implementation; this plan does not design Console-project setup for users.
- Existing reuse surfaces exist as inspected: Cloud approval mirror (`backend/config/openapi.py:338-380 approval.v1`; `activities.dispatch_pending_approvals`; `routines` approvals), Foundry error taxonomy (`foundry.py:196-252`), profile `.env` 0600 materialization (`profile_store.py:1534-1542`), Hermes skill triage + token paths (`SKILL.md:52-66`; `google_api.py:42-54`).
- Foundry continuity gates (FND-005–FND-008 per cloud-domain-map §15) are prerequisites for breadth; Gmail materialization rides the same profile lifecycle. ADV-006 makes this explicit for Phase 3: entry prerequisites are (a) FND-005–008 evidence green and (b) a joint Cloud+Foundry versioned, authenticated, bounded credential-resolution contract (ref format, command-bound expiring-ref binding — cross-command reject, same-command idempotent — expiry, error-taxonomy mapping, 0600 handling, ref-rotation → re-materialization trigger). Merge/rollout order: Foundry slice first, then Cloud `integrations` with prod flag held False, then Interface; the flag is enabled only when Phase 6 evidences slice compatibility — Cloud stays disabled until then.
- Assumptions: driving Cloud can reach Google token + revocation endpoints; token-refresh proposal is 10 s timeout + 2 bounded retries and Google revoke is best-effort async with `repair_required` on failure — numbers are confirmed against measured latency pre-rollout (AL-05 mandates categories, not values); single Gmail account per workspace in v1 (second account is a typed conflict, not silent merge); short-lived access token TTL ≈ 1h (Google default; exact value is opaque to Foundry and recorded at mint).

## Contract and Shape Definitions

Conventions: Cloud owns product truth; Foundry owns runtime truth (`BOUNDARY.md:5`). No shared Django models. Scope strings stay opaque to the kernel (watchpoint 3). Logs/traces never carry tokens (AL-09; `foundry.py:287-293` redaction pattern).

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `backend/integrations/services/gmail_oauth.py` (Cloud; new `integrations` app per D10 — exact module filename verify-only, file does not exist yet) | `begin_gmail_connect` | `begin_gmail_connect(workspace_id, user_id, entry_point, ally_id?) -> ConnectSession` | Workspace membership + capability rechecked (CLOUD-01); `entry_point ∈ {integrations, in_chat}`; `ally_id` required iff in-chat (auto-grant target); no-op when `ALLIES_GMAIL_ENABLED` is False (D11) | `ConnectSession{state_token_hash, pkce_verifier_ref, expires_at (≤10 min), auth_url}` | Creates short-lived connect session; no token stored yet; errors: `403`, `409` existing session |
| `backend/integrations/services/gmail_oauth.py` (Cloud; verify-only filename) | `complete_gmail_connect` | `complete_gmail_connect(state, code, pkce_verifier) -> GmailConnection` | Validates `state`, PKCE, Google token response; rejects scope shortfall (must include both v1 scopes); encrypts refresh at rest | `GmailConnection{connection_id, workspace_id, google_account_hash, scope_set, connected_at}` | Persists ONE generic secret row (see Data Shapes); audit event; errors: `422 scope_insufficient`, `409 duplicate_account`, `503 provider_unavailable` (bounded retry) |
| `backend/integrations/services/grants.py` (Cloud; verify-only filename) | `set_ally_grant` | `set_ally_grant(connection_id, ally_id, level) -> AllyGrant` | `level ∈ {none, read, send}` (`send ⊃ read`); grantor capability; Ally belongs to workspace | `AllyGrant{ally_id, level, grant_generation, updated_at}` | Writes grant row; bumps `grant_generation`; fence signal for in-flight (see Phase 4); `none` = row delete |
| `backend/chat/services/dispatch.py` (Cloud) wrapping `create_execution_intent` from `allies.gateways.foundry` (contracts in `allies.gateways.contracts`) | `check_gmail_grant` | `check_gmail_grant(workspace_id, ally_id) -> GrantDecision` | Called on EVERY dispatch before the `create_execution_intent(command, ...)` call-site (`dispatch.py:1217`); resolves connection + live grant row; maps level→allowlist (`send` → search/get/send/reply, `read` → search/get, none → deny/empty). Dispatch operates on the whole persisted command (`dispatch.py:1206-1217`), so this check emits the execution's allowed-operation list (SIM-001: no `requested_tool` input — the dispatcher holds the whole command, not later skill args); per-call send enforcement is the single provider-neutral gate below | `GrantDecision{allowed: bool, grant_generation, tool_allowlist[], reason_code?}` | No state mutation; denied → typed `403 grant_denied` to product, never dispatched |
| Foundry runtime tool-call boundary (Foundry slice; exact module verify-only — gate sits between agent tool invocation and skill CLI exec, skill itself stays unmodified) | `authorize_tool_call` (single provider-neutral gate; no Gmail-specific runtime authorizer) | `authorize_tool_call(execution_allowlist, tool, args_hash, approval_id?, live_grant_generation) -> allow \| deny` | `tool ∈ execution_allowlist` else deny; live grant generation still current (revocation fencing); `gmail send/reply` additionally require an `approval_id` whose bound `payload_sha256` exactly matches the canonicalized call args (ADV-003) | `allow` or `deny + reason_code (grant_denied \| approval_mismatch \| approval_missing)` | Deny blocks the tool call before it happens; mismatch never dispatches |
| `backend/integrations/services/credential_mint.py` (Cloud; verify-only filename) | `mint_execution_credential` | `mint_execution_credential(grant_decision, ttl) -> ExecutionCredential` | Requires `allowed=true` + fresh generation match; calls Google refresh→access (proposal: 10 s timeout + 2 bounded retries; numbers confirmed pre-rollout) | `ExecutionCredential{opaque_bytes_ref, expires_at, tool_allowlist}` (envelope below) | Audit mint (redacted: connection id + expiry + allowlist hash only); errors: `retryable provider_unavailable`, `repair_required refresh_revoked` |
| `allies-foundry/...` (Foundry; exact module uncertain — verify: lifecycle/materialization service owning `ProfileSeed`) | `materialize_with_credential_refs` (existing path, extended call) | Existing `materialize(seed: ProfileSeed, ...)` (`profile_store.py:2064-2071`) | `credential_refs` carries opaque references only (`_validate_credentials`, `profile_store.py:203-228`); values resolved via injected `credential_resolver` (`1605-1616`) and written to `.env` 0600 (`1534-1542`) | Existing `ProfileReceipt` (`CREATED/EXISTING/REPAIR_REQUIRED/CONFLICT/FENCED`) | No kernel OAuth parsing; unknown/oversize refs → `REPAIR_REQUIRED`; resolver failure sanitized |
| Cloud gateway + Foundry runtime | `map_credential_expiry` | Expiry exit (non-zero from skill) → terminal mapping | Matches existing `execution.terminal` registry (`status`, `reason`) + 16 KiB cap (cloud-domain-map §10) | `retryable` (transient/expiry race) or `repair_required` + `reason_code=gmail_credential_expired` | No new event kind (D7); reason code is a string field, not a kind |

### API and Transport Contracts

Controller pattern: `@api_controller("/workspaces/{workspace_id}/integrations/gmail", tags=["Integrations"])` (mirrors `@api_controller("/workspaces/{workspace_id}", tags=["Chat"])` at `backend/chat/api/controllers.py:115`). Callback is workspace-independent (state-bound).

Flag rule (ADV-005): `ALLIES_GMAIL_ENABLED=False` is a true emergency stop, not just no-new-connects. It is checked at authorization AND credential-use paths: begin-connect no-ops, callback rejects, grant writes are refused (grant reads stay honest), the dispatch wrapper denies Gmail intents, and mint refuses new mints. In-flight executions are fenced at the next lease/claim boundary via generation mismatch; already-materialized bytes expire within their short TTL and can never be re-minted. There is no per-workspace rollout variant in v1 — one global flag (this reconciles the earlier per-workspace claim, which is withdrawn as speculative).

| Consumer | Method and path / event | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Interface | `POST /workspaces/{workspace_id}/integrations/gmail/connect` | Workspace user capability; `Idempotency-Key` header is the single source of truth (body carries no key); no-op path when `ALLIES_GMAIL_ENABLED` is False | `BeginConnectRequest{entry_point, ally_id?, grant_level?}` + header | `202 {connect_session_id, auth_url, expires_at}` | `400`, `401`, `403`, `409`; safe retry same key+fp; mismatched replay (different ally/entry/level) rejected |
| Google (redirect) | `GET /integrations/gmail/callback?code&state` | `state` binding + PKCE + session cookie; workspace resolved from state and capability enforced before any mutation; rejected outright when `ALLIES_GMAIL_ENABLED` is False | OAuth callback (JSON view below) | `200` connection JSON (in-app sheet reads it; no 302 — the sheet owns navigation) | Mismatched state → reject; no retry on `invalid_grant`; provider 4xx never retried |
| Interface | `POST /workspaces/{workspace_id}/integrations/gmail/grants` | Grantor capability | `SetGrantRequest{ally_id, level: none\|read\|send}` | `200 AllyGrantResponse` | `403`, `404`, `422`; grant-generation fencing, not silent overwrite |
| Interface | `DELETE /workspaces/{workspace_id}/integrations/gmail` (account disconnect) | Workspace admin/owner capability | `DisconnectRequest{confirm: true, idempotency_key}` | `202 {disconnect_operation_id, status: scrub_queued}` | `409` in-flight fence pending → still accepts, scrubs async; see rollback |
| Cloud → Foundry | `execution.command` (existing v1 shape, cloud-domain-map §9.1) + credential envelope | Service identity; immutable `cloud_binding_id`; discriminated scope | Execution credential envelope (JSON below) | Foundry receipt (`bound`/`retryable`/`repair_required`) | Unknown timeout reconciled by command key; same key+fingerprint replays |
| Foundry → Cloud | `execution.event` (existing v1 shape §9.2) allowlisted terminal | Service identity; composite dedupe `execution:attempt:generation:event` | Approval flow events (JSON below) | Projected activity; `waiting_for_approval` → decision → dispatch | Oversize/unknown/secret-bearing → typed rejection |

Representative JSON — OAuth callback handling (Cloud-internal view; tokens never leave Cloud):

```json
{
  "schema_version": "v1",
  "kind": "gmail.oauth_callback",
  "connection_attempt_id": "conn-attempt_...",
  "scope": { "kind": "workspace", "cloud_workspace_id": "ws_..." },
  "cloud_binding_hint": "binding_... (in-chat auto-grant target ally, optional)",
  "google": {
    "code": "[redacted: single-use, never logged]",
    "granted_scopes": [
      "https://www.googleapis.com/auth/gmail.modify",
      "https://www.googleapis.com/auth/gmail.send"
    ]
  },
  "result": "connected | scope_insufficient | already_connected | provider_unavailable"
}
```

Scope-insufficiency is explicit: if `granted_scopes` lacks either v1 scope, Cloud returns `422 scope_insufficient` and stores nothing (mirrors the Hermes partial-scope signal `setup.py:240-247` but enforced server-side at consent time, not discovered later).

Representative JSON — grant check (gateway-internal decision; the wire to Foundry carries only the envelope below, never the grant table):

```json
{
  "workspace_id": "ws_...",
  "ally_id": "ally_...",
  "grant": { "level": "read", "grant_generation": 7 },
  "decision": { "allowed": true, "tool_allowlist": ["gmail search", "gmail get"], "reason_code": null }
}
```

The allowlist is the per-operation enforcement output (SIM-001): pre-dispatch reads the live grant and emits its allowed-operation list with no `requested_tool` input; the single provider-neutral gate re-checks that list + current grant generation (+ approval-bound payload match on sends) at every tool call, so a read-only execution has no send path even though the minted token itself carries both scopes. `allowed=false` only when no grant row exists; otherwise enforcement is "send absent from the list → gate denies".

Representative JSON — execution credential envelope (Cloud → Foundry; generic, provider-neutral):

```json
{
  "schema_version": "v1",
  "kind": "execution.command",
  "producer": "cloud",
  "command_id": "cmd_...",
  "idempotency_key": "intent_...",
  "scope": { "kind": "workspace", "cloud_workspace_id": "ws_..." },
  "cloud": {
    "ally_id": "ally_...",
    "conversation_id": "conversation_...",
    "intent_id": "intent_...",
    "cloud_binding_id": "binding_..."
  },
  "credential": {
    "ref": "credref_... (expiring, bound to this command_id; idempotent resolution for retries of the same command, rejected for any other command; fresh ref per execution; never persisted as bytes)",
    "expires_at": "2026-09-22T13:00:00Z",
    "tool_allowlist": ["gmail search", "gmail get"],
    "grant_generation": 7
  },
  "payload": { "kind": "execution_input", "text": "..." },
  "fingerprint": "canonical-json-sha256:v1:..."
}
```

Rules: `credential.ref` is an expiring ref bound to one `command_id` (SIM-003: no global consume-once state) — use by any other command is rejected, while retries of the same command resolve idempotently; each execution mints a fresh ref. It resolves to ACCESS-only bytes with NO `refresh_token` field. The Cloud outbox persists `command_bytes` (`dispatch.py:324-330`) — it carries the opaque ref ONLY, never access bytes (watchpoint 2: Cloud persists no attempt/session state and no secret bytes; the ref is correlation, not a credential). Foundry resolves the ref at materialization (`_resolve_credential`, `profile_store.py:1605-1616`); the EXISTING-without-rebuild path (`profile_store.py:1897-1904`) never refreshes bytes, so each execution's fresh ref changes the seed fingerprint and forces a rebuild — cross-command reuse, expired, or unknown refs fail resolution (`retryable` on mint race, `repair_required` otherwise) and the bytes can never be replayed across executions. Kernel treats `expires_at` as an opaque deadline and `tool_allowlist` as an opaque string list (watchpoint 3 — no scope parsing in Foundry/runtime); `grant_generation` mismatch at claim/dispatch → `FENCED`. Expiry, grant removal, and disconnect all requeue re-materialization/scrub so stale bytes are absent afterwards (proven by file-absence + replay-rejection tests). Next providers reuse this exact envelope with different allowlist strings — zero Foundry changes (Req 7).

Representative JSON — approval flow for send (existing mirror; draft shown before dispatch per Req 5; ADV-003 immutable binding):

```json
{ "event_type": "approval.requested", "payload": { "kind": "approval_request", "approval_id": "018f77d8-...", "prompt": "Send to bob@example.com — Subject: Q3 report — [draft body preview, ≤16 KiB]", "payload_sha256": "sha256 over canonical {to, cc, subject, body, thread_id}" } }
{ "decision": "approve | reject", "approval_id": "018f77d8-...", "decided_by": "user_...", "idempotency_key": "approval-choice_..." }
{ "event_type": "execution.terminal", "payload": { "kind": "terminal", "status": "succeeded | failed", "reason": "sent | rejected_by_user | approval_mismatch | gmail_credential_expired | gmail_send_unconfirmed" } }
```

Binding rule: the approval binds ONE immutable normalized payload (`payload_sha256`); the actual Gmail call must match exactly — any post-approval field change (recipient, subject, body, thread) is denied with `approval_mismatch` and never dispatched. When the full normalized payload exceeds the 16 KiB preview cap, v1 offers NO approval (reason `payload_too_large`): content the user cannot see is never approved — no truncate-and-approve.

Approval deadlines reuse Foundry constants (`foundry.py:70-74`: 30 s acknowledgement, 300 s lifetime, 16 KiB preview cap). Expiry of the credential mid-attempt surfaces as terminal `failed` + `reason: gmail_credential_expired` mapped to `retryable` (refresh race) or `repair_required` (revoked) — never a new event kind.

Ambiguous send outcome (ADV-004, SIM-002): when Gmail accepts a send but the response is lost, the outcome is UNKNOWABLE from the execution side — so v1 performs NO blind replay, makes NO exactly-once claim, and builds NO bespoke confirmation workflow or payload-hash Sent matcher. The execution goes terminal `failed` + `reason: gmail_send_unconfirmed` on the existing repair/reconciliation path (a `repair_required` confirmation state, not a retryable one): automatic replay is blocked, the operator sees "Gmail may have sent this — check Sent manually before doing anything", and any resend requires a manual Sent check first plus a NEW send with a NEW approval. Any retry path that re-runs delivery without that reconciliation is out of v1.

### Data Shapes and Invariants

#### Database Models

| Type / category | Model / table | Location | Fields and types | Required / nullable / defaults | Validation, indexes, constraints, and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- | --- |
| Persisted model / table | `IntegrationSecret` (generic, tenant-scoped; exact model name verify-only) | `backend/integrations/models.py` (new `integrations` app per D10 — file does not exist yet, verify at implementation) | `id UUID PK, workspace FK, provider_key str (e.g. "gmail"), account_ref_hash str, ciphertext bytes, key_version int, scope_set text[], connected_at, revoked_at nullable` | `workspace`, `provider_key`, `ciphertext`, `key_version` required; `revoked_at` nullable | CLOUD-01: every lookup resolves tenant + membership + ancestry; unique `(workspace, provider_key, account_ref_hash)`; negative cross-tenant tests required; ciphertext envelope holds refresh only — access tokens are never persisted. Encryption (ADV-007) reuses the existing Fernet seal pattern (`backend/auths/services/native_authorization.py:78-95`, same in `flows.py:81-96` — authenticated encryption with TTL-bounded unseal) under a DEDICATED vault key (env name verify-only; never the native-flow digest key — key separation); `key_version` selects the key; rotation adds a version + re-encrypts; retired keys are decrypt-only during overlap, then destroyed; missing or retired-beyond-window keys fail closed (`repair_required`, never plaintext); erasure is row delete plus the key-destruction runbook. Owner: `integrations` app | Additive table + migration; single generic row serves all future providers (Req 7: not per-provider vaults) |
| Persisted model / table | `AllyIntegrationGrant` (exact model name verify-only) | `backend/integrations/models.py` (verify-only, as above) | `id UUID PK, secret FK, ally FK, level str, grant_generation int, created_by, updated_at` | All required except audit nuances; `level ∈ {read, send}` (none = row absent) | Unique `(secret, ally)`; generation monotonic++; every dispatch re-reads live row (no cached grants); delete fences in-flight by generation | Additive table + migration; grant rows reference the generic secret, so new providers add rows, not tables |

#### Enums

| Type / category | Enum | Location | Members / representation | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- |
| Enum (persisted field vocabulary) | `GrantLevel` (exact name verify-only) | `backend/integrations/...` (verify-only filename) | `read`, `send` (`send` implies `read`) | Only listed values; `none` expressed as row absence; transitions explicit; tool→level map is Cloud-side table, never kernel logic | Additive member (e.g. future `manage`) requires contract decision |
| Enum (reason vocabulary, not event kinds) | `GmailReasonCode` (string field, exact name verify-only) | Dispatch wrapper in `backend/chat/services/dispatch.py` + event projection | `grant_denied_*`, `gmail_credential_expired`, `scope_insufficient`, `refresh_revoked`, `provider_unavailable` | Reason codes ride existing `retryable`/`repair_required`/terminal `reason`; no new event kind (D7) | Additive strings; existing clients ignore unknown reasons safely |

#### API Request Schemas

| Type / category | Request schema | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- | --- |
| API request schema / DTO | `BeginConnectRequest` | `backend/integrations/schemas.py` (verify-only filename) | `entry_point: str, ally_id: UUID?, idempotency_key: str` | `entry_point` required; `ally_id` required iff `in_chat` | Trimmed, bounded, rejects unknown fields; same key+fingerprint replays | Versioned (`v1` routes) |
| API request schema / DTO | `SetGrantRequest` | Same (verify-only filename) | `ally_id: UUID, level: read\|send\|none` | All required | Ally ∈ workspace; grantor capability; generation bump atomic with write | Versioned |
| API request schema / DTO | `DisconnectRequest` | Same (verify-only filename) | `confirm: bool=true, idempotency_key: str` | `confirm` must be true | Serialized per connection; always scrubs even with in-flight work | Versioned |

#### API Response Schemas

| Type / category | Response schema | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- | --- |
| API response schema / DTO | `GmailConnectionResponse` | Same (verify-only filename) | `connection_id, account_email (full address), scope_set[], connected_at, ally_grants[]` | No nullable fields unless stated | Product-safe scoping (ADV-008, owner-answered 2026-09-24): the FULL email address is shown because it is the user's own mailbox in their own session, visible only to workspace members with the connection capability (CLOUD-01 still applies). Wrong-account journey is full disconnect (scrub + Google revoke) then reconnect — never an in-place account swap; single-account-per-workspace stands. Never refresh/access bytes or Google `sub` beyond the address (AL-09) | Additive fields only |
| API response schema / DTO | `AllyGrantResponse` | Same (verify-only filename) | `ally_id, level, grant_generation, updated_at` | All required | Generation exposed so Interface can show "revoked, fencing in-flight" state honestly | Additive fields only |

#### Temporary / Internal Shapes

| Type / category | Shape | Location | Fields and types | Lifetime / visibility | Validation, security, and invariants | Compatibility / rotation notes |
| --- | --- | --- | --- | --- | --- | --- |
| Temporary/internal shape | `ExecutionCredential` (minted access bytes) | Cloud mint service → Foundry materialization | `opaque_bytes (form below), expires_at, tool_allowlist[], grant_generation` | Single-execution; Cloud never persists bytes — the outbox `command_bytes` hold the opaque ref only (`dispatch.py:324-330`); bytes live in profile `.env` 0600 until scrub/re-materialization | Opaque to kernel; `expires_at` enforced by skill exit mapping; allowlist enforced Cloud-side pre-dispatch AND at the single provider-neutral gate | Rotation = re-mint per execution with a fresh expiring command-bound ref; refresh stays Cloud-side (D6) |

Injected file form (the ONLY secret bytes Hermes ever sees; skill UNMODIFIED):

```json
{
  "type": "authorized_user",
  "client_id": "<allies-owned client id>",
  "client_secret": "[not shipped — field absent]",
  "token": "<short-lived access token>",
  "expiry": "2026-09-22T13:00:00Z",
  "scopes": ["https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/gmail.send"]
}
```

No `refresh_token` key is present, so `google_api.py:189` (`if creds.expired and creds.refresh_token`) can never take the refresh branch and the write-back at `:191-196` never fires (D6). On expiry the skill exits non-zero (`:197-199` `sys.exit(1)` path) → mapped per §Function table. `scopes` here is informational for the skill only; the kernel never parses it (watchpoint 3).

#### Service Primitives

| Type / category | Primitive | Location | Signature | Inputs and validation | Return value | Lock/transaction ownership, side effects, and errors |
| --- | --- | --- | --- | --- | --- | --- |
| Service operation | `revoke_ally_grant` | `backend/integrations/services/grants.py` (verify-only filename) | `revoke_ally_grant(secret_id, ally_id) -> generation` | Locked row delete + generation bump | New generation; in-flight attempts carrying older generation get `FENCED` at next lease/claim boundary | Lock owns grant row; no token deletion |
| Service operation | `disconnect_gmail_account` | `backend/integrations/services/gmail_oauth.py` (verify-only filename) | `disconnect_gmail_account(secret_id) -> operation_id` | Locked: mark revoked, delete ciphertext, call Google revoke endpoint (best-effort async; failure → `repair_required` with retry), enqueue profile re-materialization (scrub) | `scrub_queued`; receipts `deprovisioned/already_cleaned/repair_required` | Owns secret row; Google-revoke failure → `repair_required` with retry, never reported success (AL-03) |

### Plain-language glossary

- **Model / table:** persisted rows above (`IntegrationSecret`, `AllyIntegrationGrant`).
- **Schema:** validated boundary DTOs (`BeginConnectRequest`, grant/connection responses).
- **Enum:** closed vocabularies (`GrantLevel`, reason-code strings).
- **DTO:** data carried across Cloud↔Foundry (`ExecutionCredential`, envelopes).
- **Primitive:** one-state-transition operations (`revoke_ally_grant`, `disconnect_gmail_account`).
- **Index:** unique `(workspace, provider_key, account_ref_hash)` and `(secret, ally)` lookups (not separate models).
- **Constraint:** single-account-per-workspace v1 uniqueness; generation monotonicity.
- **Invariant:** grant logic Cloud-side; Cloud persists refs, never bytes or attempt/session state; scope strings opaque to kernel (watchpoints).

### Frontend Interaction Shapes (if applicable)

| UI entry point | Hook / action signature | State shape and transitions | API input/output mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| Integrations page: Gmail card | `connectGmail(): Promise<void>` → OAuth redirect → callback landing | `disconnected → connecting → connected \| scope_insufficient \| error` | `BeginConnectRequest{integrations}` → `auth_url` → redirect out and back | Loading: spinner on card; `scope_insufficient`: "Gmail needs read+send — reconnect and tick both boxes"; `403`: capability message; empty: "No Gmail connected" |
| Integrations page: per-Ally grant rows | `setGrant(allyId, level): Promise<void>` | `read \| send \| none` optimistic with rollback on `409/422` | `SetGrantRequest` → `AllyGrantResponse` (show generation-fencing notice on revoke) | Revoke shows "revoking — in-flight runs fenced"; denied capabilities hidden, not disabled-with-tooltip-only |
| In-chat: "Connect Gmail" initiation | `initiateGmailConnect(allyId): Promise<void>` → inline OAuth sheet | `idle → sheet_open → connecting → granted_to_this_ally \| error` | Same begin-connect with `entry_point=in_chat, ally_id`; success auto-creates `send`-or-`read` grant per prior user choice (default: explicit level picker in sheet, never silent max) | Sheet handles popup-blocked (fallback URL copy), expiry (≤10 min re-initiate), and `already_connected` (jump to grant picker) |

## Phases

### Phase 1 — Cloud OAuth + generic secret (lead: Cloud)

- Goal: Allies-owned Google OAuth connect/callback with minimal scopes; ONE generic encrypted tenant-scoped secret row.
- Work items: `ALLIES_GMAIL_ENABLED = env_bool("ALLIES_GMAIL_ENABLED", True)` in `backend/config/settings.py` (mirrors the `env_bool` pattern at `settings.py:570-578`); OAuth begin/callback (PKCE, `state`, new consent scope set separate from sign-in `openid profile email` at `backend/auths/providers/google.py:118`); `IntegrationSecret` model + migration + encryption envelope (Fernet seal under dedicated vault key per ADV-007 contract in §Data Shapes); in-chat initiation sheet contract showing the full account email (ADV-008); audit events (redacted).
- Impacted files/systems: `backend/config/settings.py` (one flag line); `backend/auths/providers/google.py` (extend scope handling for a SECOND consent — sign-in untouched); `backend/integrations/models.py, services/gmail_oauth.py, api/controllers/` (new `integrations` app per D10 — exact module filenames verify-only); Interface Integrations page + chat sheet (slice spec only here; implementation in follow-up repo episode per D9).
- Exit criteria: connect stores refresh with exactly the two v1 scopes; scope shortfall rejected pre-store; second account → typed conflict; `make check + make lint` pass.
- Rollout safety (D11): default-True is safe because grants default to none and every send requires OAuth consent plus an approval decision — the flag gates entry points, not authorization. Prod env holds the flag False until Phase 6 evidences slice compatibility (ADV-006 order); flipping it False later is the emergency stop (ADV-005: auth + use paths + in-flight fencing).

### Phase 2 — Per-Ally grants + gateway fence (lead: Cloud)

- Goal: grant CRUD + per-dispatch enforcement before any Foundry call.
- Work items: `AllyIntegrationGrant` model + `set_ally_grant`/`revoke_ally_grant` with generation bump; `check_gmail_grant` wrapper at the `create_execution_intent` call-site in `backend/chat/services/dispatch.py` (`dispatch.py:1217`; boundary `allies.gateways.foundry`, contracts in `allies.gateways.contracts`) on EVERY dispatch (level→allowlist map: `send` → search/get/send/reply, `read` → search/get, none → deny; SIM-001: no `requested_tool` input) emitting the execution's allowed-operation list; `grant_denied` typed UX; negative cross-tenant tests (CLOUD-01).
- Impacted files/systems: `backend/integrations/services/grants.py` (verify-only filename); `backend/chat/services/dispatch.py` (wrap the existing call-site, don't fork).
- Exit criteria: ungranted Ally's Gmail tool call never reaches Foundry (test asserts zero gateway calls); read-granted execution attempting send is denied at the single provider-neutral gate (ADV-001 + SIM-001: per-operation matrix read/send/none × search/get/send/reply — pre-dispatch emits the level-derived allowlist, each tool call gated on list + live generation + approval-bound payload on sends); grant revoke bumps generation; watchpoint 1 (grant logic Cloud-side) evidenced by code location + test.

### Phase 3 — Passthrough mint + Foundry injection (lead: Cloud + Foundry slice)

- Goal: per-execution ACCESS-only mint; opaque injection via existing `credential_refs`→`.env`; unmodified skill.
- Entry prerequisites (ADV-006): FND-005–008 evidence green AND the joint versioned, authenticated, bounded credential-resolution contract published (ref format, command-bound expiring-ref binding — cross-command reject, same-command idempotent — expiry, error mapping, 0600 handling, rotation→rebuild). No Phase 3 implementation until both exist.
- Work items: Cloud `mint_execution_credential` (refresh→access, proposal 10 s timeout + 2 bounded retries with numbers confirmed pre-rollout, redacted audit); pass `credential.ref + expires_at + tool_allowlist + grant_generation` in `execution.command`; Foundry resolves via existing `_resolve_credential` (`profile_store.py:1605-1616`) → `.env` 0600 (`1536-1542`); tool allowlist mirrors the proven `memory_tool_allowlist` pattern (`profile_store.py:292` field, `:469-492` validation): a generic opaque-string field validated syntactically only (length/charset, never scope semantics) and fingerprinted into the manifest, so the kernel stays provider-blind per watchpoint 3; write the injected file WITHOUT `refresh_token`; verify `get_credentials()` refresh branch is dead by construction.
- Impacted files/systems: `backend/integrations/services/credential_mint.py` (verify-only filename) + dispatch envelope; Foundry materialization call-site threading `credential_refs` (existing `ProfileSeed.credential_refs`, `profile_store.py:274`); NO changes to `hermes-agent/skills/productivity/google-workspace/*` (frozen).
- Exit criteria: materialized `.env`/token file contains no `refresh_token` (assertion on bytes); outbox `command_bytes` contain the ref but no access bytes; skill refresh write-back never fires in E2E (temp `HERMES_HOME` test); cross-command ref reuse is rejected while same-command retries resolve idempotently, each execution carries a fresh expiring command-bound ref, and post-cleanup file absence holds (ADV-002 proofs, SIM-003: no global consume-once state); watchpoints 2 (no attempt/session state in Cloud — mint is stateless per execution) and 3 (no scope parsing in kernel — grep + test) evidenced.

### Phase 4 — Approval-gated send + expiry mapping (lead: Cloud, Foundry event taxonomy untouched)

- Goal: every send/reply shows a draft via the existing approval mirror; credential expiry maps to existing states + reason code.
- Work items: route Gmail send/reply tool calls through approval (`approval.requested` with draft preview ≤16 KiB; 30 s ack / 300 s lifetime per `foundry.py:70-74`); approval binds the immutable normalized payload (`payload_sha256` over {to, cc, subject, body, thread_id}) and the single provider-neutral gate enforces exact match (ADV-003, SIM-001); over-cap payloads get no approval (`payload_too_large`, never truncate-and-approve); approve→dispatch (grant re-checked at dispatch, generation-fenced); reject/expire→terminal honestly; ambiguous outcome → `gmail_send_unconfirmed` on the existing repair/reconciliation path with automatic replay blocked, uncertain outcome shown, and manual Sent check required before any newly approved send (ADV-004, SIM-002: no bespoke confirm workflow or Sent hash-matcher); expiry exit → `retryable` vs `repair_required` + `reason: gmail_credential_expired` (D7).
- Impacted files/systems: Cloud activities/approval projection + chat send path (reuse; uncertain which modules — verify); Foundry tool-call gate slice (`authorize_tool_call`, single provider-neutral gate, verify-only module); Interface approval card (slice spec); NO Foundry event-kind changes.
- Exit criteria: no test path sends without an approval decision record; post-approval field change is denied (`approval_mismatch` test); over-cap payload is unapprovable (ADV-003 tests); forced post-delivery fault yields `gmail_send_unconfirmed` on the repair path with no auto-resend, uncertain outcome shown, and manual Sent check before any newly approved send (ADV-004 + SIM-002 test); approval decision replay is idempotent (same key → same outcome).

### Phase 5 — Two-level revocation + scrub (lead: Cloud + Foundry slice)

- Goal: per-Ally revoke fences in-flight; account disconnect deletes refresh, revokes at Google, scrubs profile files.
- Work items: grant delete → generation fence (`FENCED` at lease/claim boundary per `foundry.py:201-203` pattern); disconnect → locked secret purge + Google `revoke` call (best-effort async; failure → `repair_required` with retry) + requeued materialization/scrub with `deprovisioned/already_cleaned/repair_required` receipts; retention-gap behavior honest (`repair_required`, never silent success).
- Impacted files/systems: `backend/integrations/services/grants.py` + `gmail_oauth.py` (verify-only filenames); Foundry cleanup/receipt path (existing tombstone/fence machinery per `profile_store.py` cleanup sections); Interface revoked/disconnected states.
- Exit criteria: revocation proofs (below) pass at BOTH levels; post-disconnect execution attempts fail closed with `repair_required refresh_revoked`; machine-replacement continuity test passes with vault-held refresh (below).

### Phase 6 — Boundary proof + rollout (lead: Cloud)

- Goal: demonstrate BOUNDARY 6/6 + watchpoints; enable the flag only on proven slice compatibility, with rollback ready.
- Work items: ticket-test matrix (§Acceptance Criteria); rollout flag `ALLIES_GMAIL_ENABLED` (D11, Phase 1) — defaults True in every environment, prod included (feature flags default on); set it False only to switch Gmail off; no per-workspace variant in v1; emergency-stop runbook (flag False → auth/use refusal + in-flight fencing per ADV-005); follow-up repo episodes for Foundry/Interface per D9.
- Impacted files/systems: `backend/config/settings.py` + docs; no new runtime surface.
- Exit criteria: all acceptance checks green; plan review findings closed; PRs per repo opened in dependency order (Cloud → Foundry slice → Interface).

## Acceptance Criteria

1. OAuth: Integrations + in-chat connect store exactly `gmail.modify + gmail.send`; user Console projects never involved; scope shortfall → `422 scope_insufficient`, nothing stored.
2. Grants: per-Ally `read`/`send` enforced in Cloud gateway pre-dispatch AND at each tool call via the execution allowed-operation list + single provider-neutral gate (list + live generation + approval-bound payload on sends); ungranted tool call produces zero Foundry calls and a read-granted execution cannot reach send through any tool path; revoke bumps generation and fences in-flight (`FENCED`, no silent continuation).
3. Passthrough: per-execution fresh expiring command-bound refs (cross-command reuse rejected, same-command retries idempotent — no global consume-once state); outbox holds refs, never bytes; refresh/revoke/audit stay in Cloud; Foundry kernel never parses OAuth/scopes/names provider (grep + test); injected file has no `refresh_token`; skill UNMODIFIED (checksum/diff guard in test).
4. Expiry: skill non-zero exit on expiry maps to existing `retryable`/`repair_required` + `reason: gmail_credential_expired`; no new event kind exists in code or fixtures.
5. Approval: every send/reply has a prior approval decision record bound to the immutable normalized payload; actual call must match exactly (post-approval change denied); over-cap payloads are unapprovable — unseen content is never approved; draft preview shown ≤16 KiB; idempotent decision replay.
6. Revocation: per-Ally revoke + account disconnect (refresh deleted, Google revocation called, profile files scrubbed) both proven by tests below.
7. Generic: adding a second provider reuses `IntegrationSecret` + envelope with zero Foundry changes (reviewer checks: no provider-named symbols in Foundry diff); Calendar scope absent from v1 consent and allowlists.
8. Boundary: ticket tests 1–6 pass; watchpoints pinned — (a) grant logic only in Cloud gateway, (b) Cloud persists refs, never bytes or attempt/session state, (c) scope strings never enter kernel parsing.
9. Ambiguous outcome: accepted-but-response-lost sends enter `gmail_send_unconfirmed` on the existing repair/reconciliation path — automatic replay blocked, uncertain outcome shown, manual Sent check required before any newly approved send; no blind replay; no exactly-once claim anywhere in code, fixtures, or copy.
10. Emergency stop: with `ALLIES_GMAIL_ENABLED=False`, connects, callbacks, grant writes, dispatch of Gmail intents, and mints all refuse, and in-flight executions fence at the next lease/claim boundary.

## Backend Considerations (if applicable)

### Query Optimization Plan

- Hotspots/endpoints: `check_gmail_grant` (per-dispatch), grant list on Integrations page, mint (per-execution, provider-bound).
- Query-shape choices: single indexed lookup `(secret, ally)` with `select_related(secret)`; no N+1 — grant rows fetched once per dispatch, not per tool call in a turn.
- Expected query-count change: +1 indexed read per dispatch (grant check) +1 provider call per execution (mint); no per-message fan-out.
- Measurement/monitoring plan: dispatch latency histogram with grant-check segment; mint success/refresh-latency counters (redacted); alert on `refresh_revoked` rate spike (credential incident signal).

### N+1 Prevention

- Relation access map: grant → secret → workspace; Ally → workspace ancestry for CLOUD-01.
- Prefetch/select plan per endpoint/service: Integrations page prefetches grants per connection in one query; dispatch path uses one joined row read.
- N+1 regression guardrails: query-count assertion tests on grant list + dispatch check (fail on +N growth with Ally count).

### Detailed Unit Test Cases

- Happy path: connect → grant send → dispatch check allows → mint → materialize → approval → send terminal `succeeded`.
- Validation and bad input: bad `state`/PKCE; scope shortfall; duplicate account; unknown `level`; oversized/secret-shaped `credential_refs` rejected by `_validate_credentials` rules.
- Auth/RBAC boundaries: cross-tenant grant read/write denied (negative tests); grantor without capability → `403`; revoked generation → `FENCED`.
- Idempotency/retry behavior: same connect idempotency key replays; same approval decision key replays; unknown-timeout dispatch reconciles by command key; mint retry on `provider_unavailable` bounded (AL-05/AL-07), no unbounded per-record loops.
- Failure-path behavior: Google revoke failure → `repair_required` (not success); retention/scrub gap → `repair_required`; expired credential → reason-coded terminal; malformed provider JSON → safe `provider_unavailable`.

## Frontend Considerations (if applicable)

### Data Path

- User action entry: Integrations Gmail card / in-chat "Connect Gmail" / per-Ally grant picker / approval card / Disconnect button.
- Client route/component: (Interface-owned; exact paths uncertain — verify in follow-up episode) Integrations view, chat OAuth sheet, approval card, grant rows.
- Client API route/proxy: Interface → Cloud `v1` routes only (never Foundry/Hermes directly per cloud-domain-map §2).
- Backend endpoint: begin-connect, callback, set-grant, disconnect, approval decision endpoints (§API table).
- Response -> UI model mapping: connection + grants → card/rows; approval event → draft card; terminal → timeline activity.
- Error/loading/retry path: `scope_insufficient` → guided reconnect copy; `grant_denied` → "ask owner for send access"; expired sheet → re-initiate; wrong account → "disconnect (scrubs + revokes) then reconnect" (ADV-008, never in-place swap); disconnect → progress → scrubbed confirmation with repair surfacing.

### State Management Considerations

- State ownership by layer: Cloud owns connection/grants/decisions (source of truth); Interface holds ephemeral sheet/draft view state only.
- Source of truth vs derived state: grant `level+generation` displayed from Cloud response; never locally inferred permissions.
- Caching/invalidation approach: refetch grants after set/revoke/disconnect; no long-lived permission cache (dispatch re-reads live row server-side regardless).
- Concurrency and dedupe handling: idempotency keys on connect/disconnect/decisions; generation display ("revoked — fencing run #N") prevents double-revoke confusion.

## Test Plan

- Unit tests: grant matrix (read/send/none × search/get/send/reply — pre-dispatch emits the level-derived allowlist, single provider-neutral gate enforces list + live generation + approval-bound payload on sends); approval payload binding (exact-match allow, post-approval mutation denied, over-cap unapprovable); reason codes; envelope redaction (no token bytes in logs/audit/outbox — assert `[redacted]`/absence); generation fencing; scope-shortfall rejection; flag-off refusal at all five paths.
- Integration/API tests: OAuth begin/callback with stubbed Google (PKCE, state, scope validation, flag-off callback rejection); mint with stubbed token endpoint (ACCESS-only shape, no refresh persisted, expiring command-bound ref: cross-command reuse rejected, same-command retry idempotent, fresh ref per execution); gateway→Foundry envelope contract fixtures (cross-language fingerprint rule per cloud-domain-map §8.2 if touched).
- Regression checks: Hermes skill UNMODIFIED (diff/checksum guard on `skills/productivity/google-workspace/*`); Gmail folder-alias duplicate-send oracle (configure `[Gmail]/Sent Mail` mapping per `himalaya` `configuration.md:86-94` — documents why managed Gmail must not retry delivery blindly); forced post-delivery fault → `gmail_send_unconfirmed` on the repair path with NO auto-resend, uncertain outcome shown, and manual Sent check before any newly approved send (ADV-004 + SIM-002: no bespoke confirm workflow or Sent hash-matcher; replaces any exactly-once claim); temp-`HERMES_HOME` isolation E2E (real imports, real profile dirs — per hermes-agent policy) proving no refresh write-back file appears.
- Manual verification checklist: in-chat sheet on mobile-width viewport; revoke-while-running shows fenced (not sent) outcome; disconnect shows scrubbed confirmation; Google account security page shows Allies access removed.
- Commands (exact repo checks; run, do not claim):
  - Cloud: `make check`, `make lint`, `make test APP=<path>` (and `make format` when formatting is touched) — per `Makefile:30-41` and `AGENTS.md` validation.
  - Foundry slice (in its repo episode): `make check`, `make validate`, `make lint`, `make test APP=<path>` — per foundry `AGENTS.md`.
  - E2E proofs (named, required): (1) temp-`HERMES_HOME` isolation run of `google_api.py gmail search` with injected ACCESS-only token (assert refresh branch dead, no `google_token.json` rewrite); (2) ambiguous-outcome run (forced post-delivery fault → `gmail_send_unconfirmed` on the repair path, no auto-resend, uncertain outcome shown, manual Sent check before any newly approved send); (3) machine-replacement continuity with vault-held refresh (new volume + same binding → re-materialize → works without user action); (4) revocation proof at BOTH levels (grant-delete fences attempt; disconnect deletes refresh + Google revoke + profile scrub verified by file absence + failed-closed attempt); (5) freshness proof (cross-command ref reuse rejected, same-command retry idempotent, fresh ref per execution; token bytes absent from outbox and from disk after cleanup).

## Risks and Mitigations

- Risk: Refresh token theft widens mailbox access. Mitigation: single generic encrypted row (Fernet seal under a dedicated vault key with separation, rotation, fail-closed missing/retired keys — ADV-007), tenant-scoped lookups + negative tests, redacted logs (AL-09), minimal scopes; disconnect purges + Google revocation. Rollback/fallback: rotate key version, force disconnect, re-consent.
- Risk: In-flight send escapes a concurrent revoke. Mitigation: generation check at gateway pre-dispatch, approval-decision apply, AND tool-call time; `FENCED`/deny on mismatch; approval preview states generation. Rollback/fallback: revoke + audit sweep of post-revoke terminal events.
- Risk: Skill auto-refresh split-brain if a refresh token ever reaches the volume (D6). Mitigation: mint omits the field by construction + byte-assertion test + skill-frozen guard. Rollback/fallback: scrub + re-materialize all Gmail profiles; block mints until assertion passes.
- Risk: Google OAuth verification/scope sensitivity (`gmail.send` is restricted). Mitigation: minimal scopes, honest consent copy, incremental-calendar story kept out of v1 review surface. Rollback/fallback: fall back to read-only launch flag while verification completes (no code fork — same envelope, narrower allowlist).
- Risk: Duplicate sends on retry-after-delivery (Himalaya-documented class). Mitigation: approval decision idempotency + command-key reconciliation + `gmail_send_unconfirmed` on the existing repair path with automatic replay blocked, uncertain outcome shown, and manual Sent check required before any newly approved send (ADV-004 + SIM-002: no bespoke confirm workflow or Sent hash-matcher, never an exactly-once claim). Rollback/fallback: disable send allowlist via grant default-deny; reads unaffected.
- Risk: Scope creep into Calendar/IMAP-fallback/sync workers. Mitigation: v1 consent + allowlist + tests assert calendar absence; workers explicitly out of scope. Rollback/fallback: cut follow-up episodes, not v1 surface.
