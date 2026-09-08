# Approval language and response contract brief

## Objective

Deliver the Cloud-owned approval-language and durable-response contract pass for the Allies alpha-test follow-up, targeting `origin/dev` from `ft/approval-language-contract`.

## Durable checklist

- [x] AT-025: replace product-facing “runtime blocked” and blocked-action jargon with clear user language while retaining complete forced-redacted diagnostics in the technical field.
- [x] AT-028: generate Cloud-owned plain-language approval summaries with `gpt-5.6-luna`, expose them to the frontend, and retain full forced-redacted technical details as a separate disclosure; the browser never calls Luna and Luna never decides authority. Transmission remains disabled by the required default gate pending producer evidence.
- [x] Publish a versioned typed response/state contract that proves approval is durably recorded and preserves the approval-list link to the originating message/turn, without importing unrelated Foundry behavior.
- [x] Restrict model input to allowlisted forced-redacted data; require bounded structured output, no tools, timeout and budget limits, deterministic fallback, request binding, tenant/auth isolation, and privacy-safe audit logs.
- [x] Test malformed model output, timeout/provider fallback, retries/idempotency, tenant isolation, request binding, and complete-but-redacted technical disclosure through focused explanation coverage plus the existing approval decision suite.
- [x] Update versioned OpenAPI/generated contracts or fixtures used by this repository and add focused endpoint, service, and schema tests.
- [x] Validate `make check`, `make lint`, targeted `make test APP=<path>` commands, and the relevant broader test set.
- [x] Run the required independent plan reviews and implementation reviews, open a focused PR into `dev`, and do not merge it.
- [x] After PR delivery, create the requested `gpt-5.6-luna` / `max` monitoring task and record its task ID and status.

## Out of scope

- Inline file preview.
- Runtime repair.
- Unrelated latency work.
- Browser-to-model calls.
- Any new authority decision by a model.
- Unsafe or unrelated Foundry changes.

## Delivery constraints

- Work only in the Forest worktree above.
- Reuse current OpenAI client and credential conventions.
- Treat Nabu as read-only unless an accepted decision must be reconciled.
- Keep the PR coherent and reviewable, target `origin/dev`, and retain the worktree while the PR is open.
- Apply `/ponytail full`: trace the real flow, reuse existing helpers and dependencies, add no speculative abstraction or dependency, keep the fewest-file root-cause diff, and run the dedicated Ponytail review before PR delivery. Preserve every requested security, validation, accessibility, error-handling, and durable-state guarantee.
