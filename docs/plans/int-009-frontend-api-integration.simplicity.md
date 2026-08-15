# INT-009 simplicity review

Date: 2026-08-15  
Worker: `luna_worker` (`gpt-5.6-luna`, `xhigh`)  
Verdict: needs plan revision; the same-origin facade and typed Cloud boundary are justified, but the ownership and serialization choices must be explicit.

## Required revisions

- Branch CSRF behavior by path: waitlist uses the same-origin facade and `csrftoken`; existing auth retains its current `csrf_token` behavior until its separate contract is revised. Add regression tests for both.
- Keep one waitlist flow controller: TanStack Query owns the Cloud snapshot; React owns unsaved fields, current step, pending action, and retry intent. Do not create a second general-purpose store.
- Derive durable UI states from Cloud `lifecycle`; use a simple in-flight guard and one in-memory idempotency key per visible operation rather than a general queue.
- Pin exact v1 appearance fixtures and deterministic personality serialization, including ordering, delimiter, omission, and length behavior.
- Extend the existing `FieldIssue` once with the validation reason code; do not create a parallel error hierarchy.
- Exclude the UI branch Playwright tests/config/dependency; port essential assertions to Vitest/Testing Library.
- Invalidate greetings only when the Cloud generation fingerprint changes: `name`, `job`, or serialized personality. Appearance-only edits do not invalidate the greeting.
- When the feature flag is disabled, leave the static story in place and make no Cloud call. When consent is missing, fail closed only at join without exposing configuration details.
- Synchronize/archive the HTML plan under `docs/plans/` before acceptance.

## Protected complexity

- Same-origin `/api/v1/waitlist/*` facade for Cloud cookie paths and trusted-origin behavior.
- Generated OpenAPI methods plus allowlisted snapshot mapping because the pinned schema leaves response payloads open-ended.
- Revision-aware mutation followed by `GET /draft` because mutation responses are acknowledgements, not authoritative snapshots.
- In-memory per-intent idempotency keys reused on retry.

## Residual risk

Staging currently returns `503`; cookie topology and live origin admission remain conditionally verified through fixtures/manual smoke. Final consent, joined-retention, and deployment-origin values remain release decisions.
