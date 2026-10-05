# BYOS OpenCode-first: Zen/Go static keys in Foundry

## Scope
Tenants bring their own OpenCode subscription by supplying a Zen (`OPENCODE_ZEN_API_KEY`) or Go (`OPENCODE_GO_API_KEY`) key reference. Foundry carries the provider selection and opaque key ref from profile seed to materialized Hermes profile; the caller (Cloud, on-prem operator, or custom cloud) fans the single per-tenant ref into each profile seed. Hermes authenticates to OpenCode with the materialized env key — no login flow, no token refresh.

## Approach
Ride the existing opaque-reference path end to end; add no new endpoints, tables, migrations, or adapter abstractions:

1. **Seed convention (no code change expected):** `provider: opencode-zen | opencode-go`, `model` = desired OpenCode model id, `credential_refs: {OPENCODE_ZEN_API_KEY: <opaque-ref>}` (or `OPENCODE_GO_API_KEY`). Backend `_normalize_seed` (`services/profiles.py:685-719`) and runtime `_validate_credentials` (`profile_store.py:200-220`) already accept arbitrary opaque env mappings, reject plaintext values, reserve `API_SERVER_KEY`, and cap at 32 entries. `_profile_config_bytes` (`:649-656`) already writes `model.provider/default` into Hermes `config.yaml`; `.env` resolution already writes resolved secrets `0600` with symlink guards.
2. **Per-tenant fan-out (caller-side, documented):** one key ref stored once by the caller; each profile seed for that tenant carries the same ref value under the provider env name. Rotation = update the stored ref and re-provision affected profiles (seeds are immutable — `_assert_seed_compatible` raises conflict on change).
3. **Routine-probe mapping (reconcile at implementation):** the `_model_credential_name` provider→env mapping (`copilot→GH_TOKEN`, else `MODEL_PROVIDER_API_KEY`) exists on newer branches; if present in the implementation baseline, extend it to `opencode-zen→OPENCODE_ZEN_API_KEY`, `opencode-go→OPENCODE_GO_API_KEY`. If absent, skip — Hermes reads the profile `.env` directly.
4. **Verification over new code:** prove with tests that a Zen/Go seed normalizes, materializes a `0600` `.env` with the resolved key, redacts failures, and that Hermes accepts the provider. Add an operations note so on-prem use needs no Cloud.

Out of scope: ChatGPT/Codex OAuth, any session state machine, AuthAdapter ABC, tenant-key store in Foundry, rotation API, Cloud UI, billing/metering.

## Affected surfaces
- `backend/runtime/services/profiles.py` seed normalization — verify only, change only if Zen/Go seeds fail validation.
- `runtime/allies_runtime/profile_store.py` materialization — verify only (`.env` 0600, symlink rejection, fingerprint-driven re-materialization on ref change).
- Routine probe credential-name mapping — only if present in baseline.
- `docs/operations/` — new short note: provision payload shape, per-tenant fan-out, rotation-via-reprovision, key handling rules.
- Tests alongside whichever surface changes; redaction coverage for `OPENCODE_*` material.

## Acceptance
- A profile seeded with `provider: opencode-zen` + opaque `OPENCODE_ZEN_API_KEY` ref normalizes, fingerprints, materializes, and yields a Hermes `config.yaml` with that provider and a `0600` `.env` carrying the resolved key; same for `opencode-go`.
- Plaintext key pasted as a ref is rejected at validation (existing prefix guards), never persisted.
- Key material never appears in logs, events, errors, receipts, or manifests (fingerprint-only); existing redaction tests extended for the new env names.
- Changing the tenant ref and re-provisioning produces a new fingerprint and re-materializes; old key is gone from the profile (no stale `.env` merge).
- Hermes smoke: a materialized Zen/Go profile starts a session against OpenCode (or fails with a redacted provider-auth error, never a secret leak).
- On-prem operator can perform the whole flow via provision API + secret store with no Cloud dependency (docs proof).

## Validation
- `make check`, `make validate`, `make lint`, `make test APP=<touched-backend-app>`, `make runtime-test`; `make format` only if formatting changes.
- Risk-based tests, no mirrors: seed normalization accepts/rejects Zen/Go refs; materialization writes `0600` `.env` and rejects symlinked profile dirs; resolver failure → `repair_required` with redacted error; fingerprint changes on ref rotation; redaction covers `OPENCODE_ZEN_API_KEY` / `OPENCODE_GO_API_KEY`.
- Reuse results while content/env unchanged; rerun affected suites after fixes.

## Risks
- Secret leak via logs/events/receipts — mitigated by fingerprint-only evidence + redaction tests; P0 if breached.
- Operator pastes raw key instead of opaque ref — validation rejects known prefixes, but unknown key formats could persist as "refs"; docs + validation message must say `vault://`-style refs only. If the resolver ever logs the ref target, that is a leak path — verify resolver error paths stay redacted.
- Seed immutability surprise — rotation requires re-provision; documented in D5, operations note must make it unmissable.
- Hermes image drift — pinned image must contain the `opencode-zen/go` provider plugin; smoke test pins this, and the note records the minimum Hermes version.
- Scope creep into per-profile keys or OAuth — explicitly out; new episode if requested.

## Unresolved decisions
- None blocking this slice. Rotation API and ChatGPT OAuth adapter are named future episodes, not open questions here.
