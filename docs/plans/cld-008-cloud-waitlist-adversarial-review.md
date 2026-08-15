# Adversarial Review

## Verdict

Needs revision

## Findings

| Severity | Area | Finding | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| Major | Privacy-safe validation | The existing global Ninja validation handler returns `exc.errors()` verbatim. Pydantic validation errors can include the rejected input, which would expose overlong reply text, email, or personality content in the API response—contradicting the plan and canonical privacy requirements. | `backend/config/api.py::_validation_error`; CLD-008 spec, “Do not place visitor-authored content … in error details”; plan Phase 1 lists `config/api.py` but does not define redaction. | Define a waitlist-safe validation-error contract that exposes only field locations and stable reason codes, never `input` or provider details. Add regression tests using secret-like invalid values and captured logs. |
| Major | Idempotency correctness | `WaitlistOperation` stores only `result_revision`, while the plan says a retry rebuilds its response from the current draft snapshot. A later successful mutation changes that snapshot, so replay cannot be deterministic as claimed; create receipts also need an explicit pre-draft strategy. | Lavish plan, `WaitlistOperation.result_revision`: “current draft snapshot is rebuilt”; plan Requirements 6–7; CLD-008 acceptance requires safe same-key create/generation/reply/join retries. | Specify the replay contract precisely: either persist a minimal immutable, privacy-safe outcome needed to replay the original response, or make mutation responses immutable acknowledgements plus an explicit restore step. Define create idempotency as capability-bound create-or-resume after session bootstrap, and test retries both before and after a subsequent mutation. |
| Major | Provider retry and cost safety | The lease/zero-SDK-retry design does not resolve an ambiguous provider timeout: OpenAI may have accepted the request while Cloud receives no response. Retrying after a lease expires can duplicate spend, while retaining a failed receipt can make a controlled retry impossible. | Lavish plan, provider-I/O rule and Phase 2; plan Risk “Lost responses and duplicate provider spend”; CLD-008 requires controlled retry and bounded cost. | Add an explicit unknown-outcome state machine. Bind the provider request to the operation with supported provider idempotency semantics or, if unavailable, document the conservative retry policy, per-draft attempt cap, and user-visible recovery behavior. Test timeout-after-provider-acceptance, crash recovery, and lease expiry. |
| Major | Public abuse controls | The plan requires global generation admission control, but its concrete controls are capability-bound Redis limits and a local Railway bootstrap gate. Capability rotation can create new identities, and local gates are per web process rather than a distributed global budget. | Plan Requirement 15; Lavish plan “Provider cost abuse”; existing `backend/auths/api/common.py` Railway bootstrap admission is process-local. | Define a Redis-backed, atomic global generation budget/concurrency lease, per-capability limits, and a bounded unaffiliated-browser bootstrap path that fails closed on cache loss. Document settings and expiration behavior, and add multi-worker/cache-outage tests. |
| Major | Claim authorization seam | The plan requires verified matching email evidence, but the current `ExternalIdentity.email_snapshot` has no persisted verification provenance. Google currently omits unverified emails, but the fake provider stores arbitrary email text; a future claim service cannot prove the acceptance criterion from the model alone. | `backend/auths/models.py::ExternalIdentity`; `backend/auths/providers/google.py`; `backend/auths/providers/fake.py`; plan Phase 3 `claim_waitlist_draft`. | Define durable verification evidence and a single canonical email comparison routine. Either extend the existing identity record with verification provenance/source, or explicitly restrict eligible evidence to a verified provider assertion and reject all others. Reconcile this with the “two new models” decision and test unverified, stale, mismatched, and concurrent claims. |
| Major | Greeting truthfulness | The plan caps and escapes generated text but does not define the instruction template, output policy, or rejection behavior needed to prevent a greeting from claiming accounts, tools, memory, files, or completed work. Plain-text handling alone does not meet the product constraint. | CLD-008 spec, Product constraints; Lavish plan Phase 2 only rejects empty/oversized output. | Add an owner-reviewed provider instruction and explicit unsafe-output handling: reject/retry safely without storing or showing deceptive text. Add deterministic fixtures for prohibited capability claims and staging evidence for the approved prompt/version. |
| Minor | Coverage integration | Repository-wide coverage is configured only for `auths` and `workspaces`; the plan’s focused `--cov=waitlist` command does not make the normal full-suite coverage configuration include the new domain. | `backend/pyproject.toml` `[tool.coverage.run]`; plan Verification Plan. | Add `waitlist` to the configured coverage source and keep the focused threshold command as supplementary evidence. |

## Missing Questions

- Which provider-supported idempotency mechanism, if any, will the OpenAI adapter use for an ambiguous network outcome?
- What durable assertion qualifies an authenticated user’s email as verified for the future claim path?

## Plan Feedback For Revision

- Add the privacy-safe framework-validation boundary before exposing waitlist schemas.
- Replace the current receipt description with a complete replay, lease-recovery, and provider-unknown-outcome protocol.
- Specify Redis-backed global admission control separately from per-browser and bootstrap throttles.
- Define verified-email provenance and canonical comparison for the internal claim seam.
- Define and test the truthful-greeting prompt and unsafe-output path.
- Update repository-wide coverage configuration for the new application.

## Confidence

High - the review cross-checked the canonical Nabu delivery/specification records, the full plan artifacts, and the current Django API, authentication, settings, migration, dependency, and test foundations.
