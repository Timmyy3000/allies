# CLD-014 — Bring-your-own model keys (Cloud) Plan

Route: `full` (secret handling, new cross-repo trust edge). HTML: not required (owner reviews in chat).
Spec: Nabu `projects/allies/engineering/specs/byos-static-keys.md` (Proposed; owner authorized execution 2026-09-25, including the key-broker amendment below).
Companion: Foundry PR "runtime key-broker resolver" (merge order: Cloud first, then Foundry).

## Feature Overview

A workspace stores its own model-provider key once (OpenCode Zen/Go today), chooses per Ally whether it runs on that key or the org default, sees truthful status, and disconnects in one action. Key values are encrypted in Cloud and only ever leave Cloud through a broker endpoint that the Foundry backend calls on behalf of an authenticated runtime of the same workspace.

**Spec amendment (key broker).** Investigation showed the runtime can only resolve `file:///run/secrets/*` refs (Fly app secrets mounted at machine creation) or a Unix socket nothing in production serves. A Cloud `vault://` ref would never resolve. Chosen fix: refs of the form `allies-key://model-keys/<uuid>` are resolved runtime → Foundry backend (runtime token, workspace-scoped) → Cloud broker (dedicated service token, tenant-scoped). Values transit Foundry memory only; they are never persisted or logged by Foundry. "No new Foundry endpoints" is relaxed by exactly one runtime-internal endpoint.

## User Stories

1. As a workspace owner I paste my OpenCode key once and never see it again.
2. As a workspace owner I switch an Ally to my key (provider, model, reasoning) and its next reply uses it, without losing conversations.
3. As a workspace owner I disconnect my key and every Ally returns to the org default; the key is unusable immediately.
4. As a workspace owner I see "needs attention" when my key stops working, with a way back.

## Scope

### In Scope
- `common/vault.py`: provider-neutral Fernet seal/unseal with key versions (shared with the Gmail PR #55, which will import it).
- New `model_keys` app: provider registry, `ModelKey` and `AllyModelSelection` models, services, product API, internal broker endpoint, repair projection hook, retry task.
- Foundry gateway additions: install provider key, set model binding, clear model binding.

### Out of Scope
- OAuth/device sign-in providers (Codex/ChatGPT) — registry reserves `auth` kind; no code.
- Live model catalogs; billing/spend; per-conversation selection; Interface screens (INT-109).
- Gmail migration onto `common/vault.py` (belongs to PR #55).

### Dependencies and Assumptions
- Foundry v0.0.13 binding endpoints (`PUT/DELETE /api/v1/internal/profiles/{id}/model-binding`, `PUT /api/v1/internal/profiles/{id}/provider-keys`).
- Foundry profile id = `uuid5(_PROFILE_ID_NAMESPACE, str(AllyBinding.id))` — Cloud gets the namespace constant from the Foundry contract (copied, versioned in `contracts.py`), verified by a contract test against a known vector.
- Foundry stops an attempt with `execution.stopped{reason: binding_repair_required}` when a key cannot be applied or the model lock fails; Cloud already receives it.
- Companion Foundry PR adds `POST /api/v1/runtime/credentials/resolve` and the runtime `allies-key` resolver.

## Contract and Shape Definitions

### Function and Service Shapes
| Function | Purpose | Errors |
| --- | --- | --- |
| `connect_key(user, workspace_id, provider, value)` | validate, seal, store (replaces an active key for that provider: old row revoked, Allies on it re-pointed) | `ModelKeyInvalid` 422, access 404 |
| `disconnect_key(user, workspace_id, provider)` | revoke row (broker refuses at once), clear bindings of Allies on it; failed clears stay `clearing` for retry | idempotent |
| `select_model(user, workspace_id, ally_id, provider|None, model, reasoning)` | `None` → org default (clear binding); else install ref + set binding | 404 / 409 no key / 503 Foundry retryable |
| `resolve_for_broker(workspace_id, reference)` | return plaintext for an active key owned by that workspace | uniform `not_found` |
| `note_execution_outcome(ally_id, event_type, reason)` | `pending→connected` on completed; `→degraded` on `binding_repair_required` | none |
| `retry_clearing()` | Celery beat, bounded batch 25, retries pending Foundry clears | logged codes only |

### API and Transport Contracts
Product (session auth, `_require_origin`, capability `profile.read` for GET / `profile.write` for mutations, CSRF as existing controllers):
- `GET /api/v1/workspaces/{w}/model-keys` → `{providers:[{provider,label,auth,connected,fingerprint_hint,connected_at,status}]}`
- `PUT /api/v1/workspaces/{w}/model-keys/{provider}` body `{key}` → connected row (never echoes key)
- `DELETE /api/v1/workspaces/{w}/model-keys/{provider}` → `{status}`
- `GET /api/v1/workspaces/{w}/allies/{a}/model` → `{source: org_default|own_key, provider, model, reasoning, status}`
- `PUT /api/v1/workspaces/{w}/allies/{a}/model` body `{provider|null, model?, reasoning?}`

Internal (Foundry → Cloud): `POST /api/v1/internal/credentials/resolve`, `Authorization: Bearer ALLIES_CREDENTIAL_BROKER_TOKEN` (≥32 bytes, required outside debug, distinct from every other token), body `{version:1, workspace_id, reference}` → `200 {value}` with `Cache-Control: no-store`; `404 credential_unavailable` for unknown/revoked/other-tenant/bad-format (indistinguishable); `401` bad token. Body ≤ 1 KiB.

### Data Shapes and Invariants
#### Database Models
- `ModelKey`: `id uuid`, `workspace FK CASCADE`, `provider str(32)`, `ciphertext bytes`, `key_version int`, `fingerprint char(64)` (HMAC-SHA256 of value under vault key, for display/dedupe only), `created_by FK SET_NULL`, `connected_at`, `revoked_at null`. Unique active `(workspace, provider) WHERE revoked_at IS NULL`. On revoke, ciphertext is wiped to `b""`.
- `AllyModelSelection`: `ally OneToOne CASCADE`, `model_key FK SET_NULL null`, `provider`, `model`, `reasoning`, `status`, `foundry_generation int`, `updated_at`. Absence of a row = org default.
#### Enums
- `SelectionStatus`: `pending` (Foundry accepted; not yet proven by a reply), `connected`, `degraded` (repair required), `clearing` (disconnect accepted, Foundry clear not yet confirmed).
- Registry `PROVIDERS`: `opencode-zen → OPENCODE_ZEN_API_KEY`, `opencode-go → OPENCODE_GO_API_KEY`; `auth="static_key"`.
#### API Request Schemas
- key: 16–512 chars, no whitespace/control chars. model: `[A-Za-z0-9._:/-]{1,128}`. reasoning: `default|high|xhigh`.
#### API Response Schemas
- `fingerprint_hint` = last 4 hex of fingerprint. Never key bytes.
#### Service Primitives
- `seal_secret(str)->(bytes,int)`, `unseal_secret(bytes, key_version)->str` in `common/vault.py`; key from `ALLIES_VAULT_KEY[_V<n>]`, 32-byte urlsafe-b64 required, debug-only fallback when `settings.DEBUG`.

### Plain-language glossary
- **Ref**: `allies-key://model-keys/<id>` — a pointer, safe to log; meaningless without the broker.
- **Broker**: the only code path that returns a key value.

## Phases
### Phase 1 — vault + model + broker
Exit: broker returns value only for same-workspace active key; cross-tenant/revoked/garbage → identical 404; tests.
### Phase 2 — Foundry gateway + services + product API
Exit: connect/select/disconnect/status work against a faked Foundry; cross-tenant negative tests; retryable Foundry leaves honest state.
### Phase 3 — projection hook + retry task
Exit: stopped/binding_repair_required → degraded; completed → connected; `clearing` rows converge.

## Acceptance Criteria
- Key value never appears in responses (except broker), logs, exceptions, or DB plaintext; test asserts on captured logs.
- Broker: wrong token 401; other workspace, revoked, malformed → same 404 body.
- Select own key → Foundry receives install(env, ref) then set-binding(provider, model, reasoning); status `pending`.
- Select org default / disconnect → Foundry clear-binding; revoked key unresolvable even if clear fails.
- Replace key → new ref installed on every Ally using that provider.
- `make check`, `make lint`, `make test APP=model_keys` (+ touched apps) pass.

## Backend Considerations
- Fan-out bounded: an owner's Allies per provider are few; loop capped at 100 per request, remainder left `clearing` for the task.
- Foundry calls happen outside DB transactions; row state written before (intent) and after (result).

## Test Plan
Unit/API tests in `backend/model_keys/tests/`: vault round-trip and bad-key; registry validation; connect/replace/disconnect; select paths incl. Foundry retryable/conflict; broker auth + tenant isolation + revoked; projection hook; retry task; log redaction.

## Risks and Mitigations
- **Broker is a secret-exfil path (P0).** Dedicated token, tenant check against Foundry-authenticated workspace, uniform 404, no-store, no logging of value or ref target, size bounds.
- **Foundry transit.** Value in Foundry memory only; companion PR adds redaction tests.
- **Profile-id derivation drift.** Contract test vector; failure is `not_found` from Foundry, surfaced as 503, never silent.
- **PR size (~1k lines).** Kept as one PR: vault, model, broker and API are only testable together; Foundry side is separate.

## Open decisions (non-blocking)
- Model list per provider is free text for now; Interface may ship a suggested list (Timi).

## Review reconciliation (2026-09-25)

Accepted: SIM-3 (store `key_hint` = last 4 chars; no HMAC fingerprint), SIM-4 (no Ally GET; `GET model-keys` also returns per-Ally selections; no `auth`/`label` in responses), SIM-5 (registry is a plain dict), SIM-6 (`MultiFernet` over `ALLIES_VAULT_KEYS`, comma-separated newest-first; no `key_version` column), ADV-2/3 (workspace from the runtime token; Cloud resolves only an active key of that workspace that some Ally currently selects — see code-review reconciliation), ADV-4 (one atomic `PUT model-binding` carrying `key_refs`; Foundry companion PR adds `key_refs` to the HTTP schema), ADV-5 (status transitions only from messages created after `synced_at`), ADV-7 (row locks + `revision` compare-and-set), ADV-9 (unknown outcome = unsynced; retried), ADV-10 (log/exception redaction tests).

Rejected/modified: SIM-1/SIM-2 — replaced, not dropped. Per ADV-1/ADV-8, clearing must be enforced because the applied key lives in the profile `.env` until Foundry's binding generation changes. Model becomes *desired state + sync flag*: `AllyModelSelection` holds the desired selection (`model_key` null = org default) and `synced`. One idempotent `push_selection` sends it to Foundry; a beat task (`model_keys.sync_selections`, 30 s, batch 25, max 10 attempts then `degraded`) retries unsynced rows. Replace and disconnect just mark affected rows unsynced. Org-default rows are deleted once the clear is confirmed.

Honest guarantee (ADV-1): after disconnect the broker refuses the key immediately; the key leaves an Ally's volume on that Ally's next turn after Foundry accepts the clear.

Statuses exposed: `pending` (unsynced or synced but unproven), `connected`, `degraded`. ADV-6 verified: both contracts carry `execution.stopped.payload.reason` (Cloud `contracts.py` `_safe_code`, Foundry `events.py:176`).

Merge order changes: Foundry PR first (resolver + resolve endpoint + `key_refs` in binding schema), then Cloud.

## Code-review reconciliation

- CR-1 (profile-scoped broker) — not adopted; the ADV-2/3 line above is corrected here. All profiles of a workspace run in one runtime process on one machine volume, and the runtime resolver has no trustworthy profile identity, so a per-profile check would add no boundary. The broker is workspace-scoped: Foundry derives the workspace from the runtime token and requires the ref to be bound to one of its profiles; Cloud requires the same workspace, an active key, and at least one Ally in that workspace currently selecting it.
- CR-2 — adopted: only a missing/retiring profile (Foundry 404/422) drops a clearing row. Per enkii review, 409 conflicts are retried like other transient failures (bounded, then `degraded`); 401 rejections park the row as `degraded`.
- CR-3 — adopted in the Foundry PR: the blocking resolver no longer waits past its timeout.
