# BYOS static keys: live install + model binding + disconnect

## Scope
A tenant installs their own OpenCode key into a live Ally profile, selects provider/model/reasoning, and disconnects back to the org default — all without reprovisioning and without sessions being lost. Static API keys only (`OPENCODE_ZEN_API_KEY`, `OPENCODE_GO_API_KEY`). Device-code/OAuth explicitly out. Cloud polls Foundry; Foundry owns state; Hermes does the switching.

## Approach
1. **Binding (backend):** nullable `model_override` JSON on `RuntimeProfile` (`{provider, model, reasoning?}`, all optional; null = org default from deployment settings). New endpoints in `backend/runtime/api/register.py` beside the receipt endpoints: set binding (validate provider/model/reasoning shape + bounds), clear binding (disconnect selection), install key (env-name + opaque ref only, never the value), remove key. Key values never enter Foundry — caller stores the value in the secret store, passes the ref; runtime resolves via the existing resolver.
2. **Claim carries effective selection:** `services/claims.py:365` resolves override-or-seed-default for model, plus provider and bounded `model_options` (object, size-capped, allowlisted keys). Claim `__repr__` stays redacted.
3. **Runtime forwards per turn:** `hermes.py` `stream()`/`stream_profile()` accept optional provider/model/options and include them in the chat body (Hermes honors them natively per request). Thread through `_stream_events` and `coordinator` proof path. No Hermes change.
4. **Live-apply writer (runtime):** new `ProfileStore.apply_binding` — under the existing profile lock, at turn boundary only: re-resolve key refs, rewrite `.env` fully (same full-rewrite semantics as `_build_profile`, `0600`), update `config.yaml` model section when provider changes, record applied generation in a sidecar (`.allies-binding.json`) for idempotency. Never interrupts an active lease; failure → `repair_required` with redacted error, profile keeps last-good files.
5. **Disconnect:** clear binding (null → org default on next turn) + remove key ref (live-apply rewrites `.env` without it). Revert is the same machinery as install, not a special case.
6. **Trigger without polling:** selection travels in the per-attempt claim (backend resolves override-or-default at claim creation — always fresh, no new runtime→Foundry read path). Key install/removal travels as a pending-binding-generation on the profile row; the worker applies it pre-turn under its lease, gated on the profile already being materialized (else it defers to startup reconciliation, avoiding any first-boot race).

Out of scope: OAuth/device-code, per-conversation (vs per-Ally) selection, rotation API beyond re-install, Cloud UI, billing/metering, routine-probe mapping (absent on this baseline).

## Affected surfaces
- `backend/runtime/models.py` + migration: `RuntimeProfile.model_override` nullable JSON.
- `backend/runtime/api/register.py` + `schemas.py`: set/clear binding, install/remove key endpoints (runtime-authenticated, audited, redacted).
- `backend/runtime/services/claims.py`: effective model/provider/options resolution.
- `runtime/allies_runtime/hermes.py`: optional per-turn override in chat body; `fake.py` mirror for tests.
- `runtime/allies_runtime/profile_store.py`: `apply_binding` writer + sidecar generation.
- `runtime/allies_runtime/foundry.py`: carry binding through desired state + worker dispatch.
- `docs/operations/byos-opencode-keys.md`: extend with live install/select/disconnect runbook + rotation-via-reinstall note.
- Tests alongside each surface; redaction coverage for new fields.

## Acceptance
- Install key → next turn uses it (live-apply receipt + Hermes provider-auth success); Hermes profile files on volume carry the key `0600`, never in logs/events/manifests.
- Set binding → subsequent turns carry provider/model/options; clear binding → turns revert to org default with no profile change.
- Disconnect removes the key from the volume (no stale `.env` merge — full rewrite) and reverts selection.
- Switch happens only between turns; an active turn is never interrupted (lease-fenced test).
- Plaintext value sent as ref is rejected; oversized/malformed binding rejected; resolver failure → redacted `repair_required`, last-good files intact.
- On-prem operator performs install/select/disconnect via API + secret store with no Cloud.

## Validation
- `make check`, `make validate`, `make lint`, `make test APP=<touched-app>`, `make runtime-test`; `make format` only if needed.
- Risk-based tests, no mirrors: binding validation accepts/rejects; claim resolves override-or-default; stream body carries override and redacts; live-apply writes `0600`, rejects symlinks, records generation, refuses mid-lease; disconnect removes key + reverts; redaction covers new fields and error paths.
- Reuse results while content/env unchanged; rerun affected suites after fixes.

## Risks
- Secret leak via new endpoints/events/receipts — fingerprint-only evidence + redaction tests; P0 if breached.
- Partial write corrupts live profile — atomic temp-write + publish (existing pattern), failure keeps last-good; never write in place.
- Binding/model drift vs Hermes lineup (unknown model id fails at chat time) — fail closed with redacted provider error + re-select signal, never silent fallback to a different provider (that would spend the wrong account).
- Scope creep into OAuth or per-conversation selection — explicitly out; new episode.

## Unresolved decisions
- None blocking. `model_options` key allowlist is defined at implementation from Hermes' accepted keys.
