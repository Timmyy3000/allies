# Fix stuck `Waking up`: bound the speculative wake hint

## Scope

- Interface web only: `apps/web/app/home/conversation-frame.tsx`, `apps/web/app/home/conversation-frame.test.tsx`.
- Out of scope: Foundry readiness tuning, Cloud intent forwarding, new status strings, polling/SSE, avatar motion assets.

## Current behavior

Typing the first meaningful draft fires one content-free `composing_started` intent (`useComposingRuntimeIntent`, one-shot per ally view). When it settles to `waking`, `ConversationFrame` shows `Waking up` until confirmed work, a completed reply, or a `ready`/`already_ready` status — none of which arrive before send, because FND-009 caps the client at two same-key POSTs and Foundry replays the stored outcome for a repeated key. The hint latches indefinitely. On send the authoritative path accepts immediately, so the UI jumps straight to `Thinking..`.

## Approach (ponytail: one timer, no new machinery)

1. Add a bounded speculative-hint timer in `ConversationFrame` (`WAKE_HINT_TIMEOUT_MS`, proposed 30s, exported for tests):
   - Arm while any unsettled speculative status is showing (`requesting`/`waking`, plus settled-neutral `failed`/`rate_limited`/`first_provision_required`/`disabled` which also render `Waking up` today), not sleeping, and not `model.gettingReady`.
   - On expiry, treat the wake as settled-to-idle: same rendering as `ready` (avatar `idle`, no status text, composer unchanged and sendable).
   - Disarm the pending timer on status/sleep/gettingReady change; the latched value self-invalidates when the status moves on (expiry applies only while the latched status still matches).
   - Never expire authoritative `gettingReady` (provisioning `pending`/`retryable`): that `Waking up` stays until the ally binds.
   - No render loop: key the timer effect on `[runtimeIntentStatus, sleeping, model.gettingReady]` only — never on the derived `waking` boolean the expiry feeds back into. Evaluate the authoritative overrides (`gettingReady`, confirmed work, received reply, sleep) at render time.
2. Rejected: client re-poll with same key (replays stored `waking`), new key (violates the two-POST contract), SSE/readiness subscription (new infra), new `awake` string (contract + idle mapping already cover it).
3. Tests (`conversation-frame.test.tsx`, fake timers):
   - `waking` clears to idle after the timeout; avatar `data-state="idle"`, no `Waking up` role, textbox enabled.
   - `gettingReady` keeps `Waking up` past the timeout.
   - Timer resets when the intent status changes; existing ready/send/thinking cases unchanged.

## Affected surfaces

- Thread presence row (`Waking up` vs nothing), avatar state (`idle`), mute flag (`muted={docked || waking}` unmutes on expiry).
- Composer/submit path untouched: send stays enabled throughout, `Thinking..` still driven only by confirmed work.

## Acceptance

- Type → `Waking up` shows; without sending, it clears to idle within the bound while the draft remains.
- Genuinely provisioning ally keeps `Waking up` until bound.
- Send before/after expiry behaves exactly as today (`Thinking..` on confirmed work).
- `bun run lint:web` clean; targeted `conversation-frame` + `runtime-intent` suites green; no existing wake/sleep test regresses.

## Validation

- `bun run lint:web` from repo root (scoped).
- Targeted unit suites for `conversation-frame` and `runtime-intent` in `apps/web`.
- Manual: type in composer on a sleeping ally, wait out the bound, confirm idle; send, confirm `Thinking..`.

## Risks

- Timeout value is a judgment call: too short hides genuine wakes, too long keeps the complaint. 30s matches the 30s sleep-clock cadence and sits well under the 120s intent TTL. Owner may tune the constant without changing the mechanism.
- Expiring to idle while a wake is genuinely in flight slightly understates activity, but the hint is speculative by contract and send is never gated — strictly more truthful than an indefinite latch.

## Rollback

Revert the single commit. No migration, no contract change, no cross-repo dependency.

## Unresolved decisions

- Timeout value (proposed 30s) — owner confirms or tunes.
