# Simplicity Review

## Verdict

Simplification recommended

## Findings

| Classification | Plan area | Evidence | Recommendation | Preserved outcome |
| --- | --- | --- | --- | --- |
| Keep | Capability, origin/CSRF, and normalized unavailable behavior | The accepted CLD-008 specification requires a browser-bound capability, credentialed trusted-origin arrangement, and non-enumerable absent/unauthorized state. | Retain the HttpOnly capability digest, exact origin/CSRF checks, and one unavailable response. | Refresh restoration without exposing or making a draft enumerable. |
| Keep | Lifecycle, revision, and operation-receipt states | The specification explicitly requires the seven lifecycle distinctions; accepted adversarial findings require immutable retry acknowledgements and conservative unknown provider outcomes. | Retain the seven draft states and the minimal `in_progress` / `succeeded` / `failed` / `outcome_unknown` receipt protocol, including `result_revision` and `result_lifecycle`. | Stale-write safety, deterministic replay, and no automatic duplicate model spend. |
| Simplify | Appearance snapshot fields | The accepted specification requires stable appearance keys, but does not require Cloud to separately own `catalog_version`, `shape`, and `color`; the plan says Cloud does not interpret these values. | Replace `appearance_shape` and `appearance_color` with one bounded opaque `appearance_key`, retained with `appearance_catalog_version`. Align the pre-publication OpenAPI contract with Interface. | Exact restoration of the Interface-owned appearance selection without Cloud acquiring presentation semantics. |
| Simplify | Greeting provenance fields | The accepted specification and adversarial disposition require truthful-output policy versioning, not durable per-greeting provider/model history. The alpha has one configured OpenAI adapter. | Do not persist separate `greeting_provider` and `greeting_model` fields. Retain the input fingerprint, generated timestamp, text, and approved policy version. | Safe bounded generation and policy accountability; provider/model history can be added only if an operational use case emerges. |
| Simplify | Admission implementation ownership | The Lavish plan names both `waitlist/admission.py` and `waitlist/services/admission.py`, while the required three admission layers are one concern. | Use one narrowly scoped admission module with explicit bootstrap, per-capability, and global-generation operations; do not create a generic rate-limiting framework or a second owner. | Redis-atomic, fail-closed abuse and cost controls across web processes. |
| Keep | Three Redis admission layers | The accepted adversarial review specifically found process-local/bootstrap-only controls insufficient; CLD-008 requires creation limits, generation limits, and cost control. | Retain network-aware bootstrap admission, per-capability limits, and the distributed global generation lease; cache loss must fail creation/generation closed. | Resistance to capability rotation, multi-worker abuse, and unbounded provider cost. |
| Keep | Global validation redaction | `config/api.py` currently returns `exc.errors` verbatim, and CLD-008 explicitly requires a privacy-safe replacement with auth/account compatibility coverage. | Retain one global sanitizer returning only field locations and allowlisted codes; do not create waitlist-only error handling. | No visitor content or secret-like rejected input in public validation details. |
| Simplify | Fake-provider verification work | The claim requirement is that fake and unverified evidence are ineligible. A fake verified-assertion/provenance mode has no alpha value. | Extend the shared verified-identity path and Google adapter to carry durable verification evidence; keep the fake provider explicitly unverified by default and test rejection directly. | Claim cannot rest on email equality, arbitrary fake email text, or unverifiable evidence. |
| Keep | `ExternalIdentity` provenance and internal claim seam | Current `ExternalIdentity.email_snapshot` has no verification provenance, while the accepted specification requires authenticated, verified, matching, confirmed claims. | Retain the additive verification status, timestamp, and allowlisted provenance fields plus the internal locked claim service; expose no public claim endpoint. | Future safe transfer without accounts, automatic claims, or a third waitlist model. |
| Keep | Narrow synchronous provider port and output policy | The specification requires bounded provider-neutral generation, and the accepted adversarial review requires instruction/versioned output rejection. | Retain one small provider protocol, deterministic fake, synchronous eight-second adapter, and deterministic policy rejection; do not add queues, fallback greetings, or provider registries. | One truthful personalized greeting without runtime or downstream execution. |
| Remove/Defer | Numeric query-count and query-plan test guardrails | The Lavish plan adds fixed query-count assertions despite no repository query-budget convention and no collection endpoint; CLD-008 requires concurrency and bounded cleanup, not micro-performance certification. | Remove exact query-count assertions and “one lookup” guarantees. Retain the stated indexes, bounded cleanup, and PostgreSQL race tests; profile only after evidence of a performance issue. | Predictable single-draft access without brittle tests coupled to ORM internals. |
| Remove/Defer | Waitlist-specific Railway rollout machinery | Existing staging operations already define web, worker, beat, migrations, and the Cloud queue. CLD-008 needs a scheduled cleanup task and staging contract, not a new topology. | Do not make Railway documentation changes or a waitlist-specific web/worker/beat enablement sequence a primary deliverable. Add the bounded beat entry and use the established staging deployment path; update operations documentation only if a real process or environment contract changes. | Scheduled cleanup and staging OpenAPI proof without expanding operational scope. |

## Protected Complexity

- The receipt `outcome_unknown` state and explicit new-key recovery must remain: it is the smallest honest response to an ambiguous provider timeout without provider-side deduplication.
- Redis-backed bootstrap, capability, and global-generation admission controls must remain separate by identity scope; collapsing them would reintroduce the accepted multi-worker/capability-rotation abuse gap.
- The global validation sanitizer must remain global because the existing framework handler affects auth/account endpoints as well as waitlist input.
- Verified-email provenance on `ExternalIdentity` and explicit confirmation must remain; email comparison alone cannot authorize a claim.

## Plan Feedback For Revision

- Collapse appearance storage to version plus one opaque selection key, and remove provider/model persistence while retaining policy-version evidence.
- Establish a single admission owner/module for all three required Redis controls.
- Narrow fake-provider changes to explicit ineligibility; do not create fake verified-identity behavior.
- Remove query-budget assertions and waitlist-specific Railway rollout/documentation work from the implementation scope.
- Keep deployment settings limited to actual release gates and operational limits; do not externalize fixed internal constants or introduce a rollout framework.

## Residual Risk

- An opaque appearance key requires Cloud and Interface to agree on its versioned representation before publishing OpenAPI.
- Omitting historic provider/model fields reduces forensic detail after a future model change; the retained policy version and timestamp are sufficient for this alpha.
- Without fixed query-count tests, later ORM regressions rely on code review, indexes, and staging observation.

## Confidence

High - the review cross-checked the accepted Nabu ticket/specification and epic state, revised brief and Lavish plan, adversarial dispositions, kickoff configuration, and current Cloud API, model, throttle, Celery, and staging conventions.
