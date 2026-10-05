# Editorial comparison

## Revision 2: accepted simplicity findings

Better Docs and Humanizer reviewed the full revised plan, preserving safety, authority, scopes, limits and conditions. SIM-001 removes constant-value endpoint configuration; SIM-002 keeps canonical binding metadata internal and removes redundant DTO layers; SIM-003 limits new tests to explanation/contract risks and cites unchanged decision/delivery/auth/race tests. SIM-004 and SIM-005 retain the JSON fallback/CAS and private bounded shared-cache slots. Conditional portable contract fixtures remain conditional. The accepted Markdown was regenerated into both byte-identical HTML copies; all 35 plan headings and section text passed parity. Existing layout/audit limitations remain recorded. No interactive session or product tests were started.

```diff
-Status: proposed for independent review; revision 1 addresses accepted ADV-001 through ADV-004.
+Status: accepted and ready for implementation under existing user authorization; revision 2 incorporates ADV-001 through ADV-004 and SIM-001 through SIM-005. Provider transmission remains disabled until the specified redaction evidence is recorded.
```

```diff
-Credentials, rich-approval availability and a valid endpoint never enable summary transmission by themselves.
+Credentials and rich-approval availability never enable summary transmission by themselves.
```

```diff
-`generate_explanation(source: ExplanationInput) -> ExplanationFields`
+`generate_explanation(source: dict) -> validated explanation fields`
```

```diff
-approval-specific fixed HTTPS endpoint validation at startup and immediately before I/O; redirect-rejecting urllib opener.
+hard-coded `https://api.openai.com/v1/responses` constant; redirect-rejecting urllib opener; no endpoint setting or override.
```

```diff
-<JSON of allowlisted ExplanationInput>
+<JSON of allowlisted source fields>
```

```diff
-<closed schema for ExplanationFields>
+<closed schema for provider explanation output>
```

```diff
-Implementation supplies the actual JSON Schema object from the strict type, with all fields required and additional properties forbidden.
+Implementation supplies one closed provider-output schema, with all fields required and additional properties forbidden. Reuse the public explanation field validation where compatible; do not add separately named input/output DTO layers that merely copy dictionaries.
```

```diff
-version fixed, request UUID, SHA-256 preview digest, canonical input_fingerprint, action_kind, policy_version, source, action/target/consequence/reason
+version fixed, request UUID, SHA-256 preview digest, source, action/target/consequence/reason
```

```diff
-| Provider input DTO | ExplanationInput | Request UUID, preview digest, action_kind from gateway allowlist, policy_version, canonical input_fingerprint, and complete forced-redacted preview only.
+| Internal provider input | Allowlisted dictionary | Request UUID, preview digest, action_kind from gateway allowlist, policy_version, canonical input_fingerprint, and complete forced-redacted preview only.
```

```diff
-| Provider output DTO | ExplanationFields | Exact echoed request UUID, preview digest and input_fingerprint plus four required fields.
+| Internal provider output | Closed structured output | Exact echoed request UUID, preview digest and input_fingerprint plus four required fields.
```

```diff
-Cloud supplies version/source itself.
+Cloud supplies version/source itself. Persist canonical input_fingerprint, action_kind and policy_version internally; omit those three fields from the public explanation. Public action_kind exists only in technical_details.
```

```diff
-Use existing server-side OpenAI key and URL conventions;
+Reuse the existing server-side OpenAI credential convention and stdlib transport approach; hard-code the sole Responses URL in the approval module;
```

```diff
-Missing key, invalid endpoint, exhausted deadline, oversize material or unsupported source chooses fallback.
+Missing key, exhausted deadline, oversize material or unsupported source chooses fallback.
```

```diff
-Transport (ADV-002): construct `urllib.request.build_opener` with an approval-specific `HTTPRedirectHandler` whose `redirect_request` refuses every redirect. Do not use plain `urlopen`, which follows redirects by default. Approval-specific settings validation requires the exact normalized URL `https://api.openai.com/v1/responses`: HTTPS, exact host/path, default port, no userinfo, query, fragment, alternate host or custom proxy endpoint. Reject an invalid configured endpoint at startup even while the gate is off, and revalidate immediately before request construction so runtime settings overrides cannot bypass it. Do not rely solely on waitlist settings checks. Treat all 3xx responses as provider_error with fallback; never issue a second request or forward Authorization to Location. Leave waitlist transport and policy unchanged.
+Transport (ADV-002, simplified by SIM-001): construct `urllib.request.build_opener` with an approval-specific `HTTPRedirectHandler` whose `redirect_request` refuses every redirect. Use the hard-coded constant `https://api.openai.com/v1/responses` when constructing every request. There is no approval endpoint setting, environment override, startup validator or runtime override validator. Do not use plain `urlopen`, which follows redirects by default. Treat all 3xx responses as provider_error with fallback; never issue a second request or forward Authorization to Location. Tests inspect the constructed request URL constant and prove other settings cannot redirect approval calls. Leave waitlist transport and policy unchanged.
```

```diff
-Extend existing approval tests for endpoint/state/races and add focused explanation tests for provider boundaries.
+Add only explanation and changed-contract tests. Parameterize related invalid-output, redirect, budget, binding and gate cases. Reuse the existing decision, delivery, authorization and PostgreSQL race tests unchanged as regression evidence; extend one only when the implementation changes the behavior it exercises.
```

```diff
-Measure query counts for one versus 50 list results and repeated detail.
+Add query-count measurement only if implementation introduces a new relation traversal; otherwise reuse the existing selected relations without a new performance test.
```

```diff
-Auth/RBAC: foreign workspace, foreign conversation/message/approval, inactive membership, read-only decision capability, browser CSRF/origin failure, native session and mixed transport, membership revoked while model waits. No unauthorized provider call or disclosure.
+New authorization coverage is limited to the explanation boundary: parameterize foreign scope/inactive membership and assert no provider call or disclosure; test membership revoked while model waits. Existing `test_approval_detail_and_list_are_membership_scoped`, `test_approval_api_requires_auth_and_write_capability`, `test_approval_api_rejects_foreign_scope`, and `test_browser_decision_requires_csrf_and_native_bearer_can_decide` remain broader evidence for unchanged access/decision transport. Do not duplicate their matrices.
```

```diff
-exact decision retry returns saved choice, changed key/choice conflicts; two PostgreSQL decision requests have one first winner.
+reuse existing `test_approval_decision_is_first_wins_and_exact_retry_replays` and `test_concurrent_decisions_have_one_first_winner` for unchanged decision semantics;
```

```diff
-transport errors/429/5xx/invalid endpoint
+transport errors/429/5xx
```

```diff
-Startup and runtime endpoint checks reject malicious or altered URLs independently of waitlist configuration.
+Inspect the constructed Request.full_url for the exact hard-coded URL and verify unrelated endpoint settings have no effect; there is no endpoint override feature to test.
```

```diff
-Existing delivery deadlines and late resolution behavior remain valid.
+Existing delivery deadlines and late resolution behavior remain valid, using the existing receipt-identity, bounded retry, exhausted-attempt, acknowledgement-deadline, consent-recheck and late-resolution tests in `test_approval.py` without recreating them.
```

```diff
-5. Allowlisted forced-redacted input, strict bounded output, one-attempt and aggregate tenant/global budgets, total deadline, fallback, canonical input fingerprint, default-off summary enablement, redirect rejection, tenant isolation and privacy-safe audit evidence all have failure tests.
+5. Allowlisted forced-redacted input, strict bounded output, one-attempt and aggregate tenant/global budgets, total deadline, fallback, internal canonical input fingerprint, default-off summary enablement, constant endpoint/redirect rejection, tenant isolation and privacy-safe audit evidence all have focused failure tests.
```

```diff
-Public explanation | New strict schema in same schema module or focused explanation module
+Public explanation | One strict public schema in the existing schema module or focused explanation module
```



## Revision 1: accepted adversarial findings

Better Docs and Humanizer reviewed the complete revised Markdown. The following changes are substantive accepted review corrections, not editorial reinterpretations. Subsequent wording passes preserved every new limit, default, conditional, test and prior requirement. `global cache` was clarified to `global content cache` so reuse of the existing limiter cache is unambiguous. Markdown-to-HTML text parity passed for all 35 plan headings; the unchanged lifecycle diagram is additional presentation. Both HTML copies were regenerated from the final revised Markdown and are byte-identical.

```diff
-Status: proposed for independent review.
+Status: proposed for independent review; revision 1 addresses accepted ADV-001 through ADV-004.
```

```diff
-sanitized operational fields; no OpenAI SDK dependency.
+sanitized operational fields; no OpenAI SDK dependency. Adjacent revision evidence: `backend/auths/throttle.py`, `backend/auths/tests/test_throttle.py` and shared Redis/LocMem configuration in settings provide existing fail-closed per-identity/global counters.
```

```diff
-The authenticated v1 rich event promises a complete forced-redacted preview of at most 16 KiB UTF-8.
+`ALLIES_APPROVAL_SUMMARIES_ENABLED` defaults to false. Credentials, rich-approval availability and a valid endpoint never enable summary transmission by themselves. Enable this dedicated gate only after recording the exact producer revisions and redaction test paths/results for terminal, execute-code and plugin-tool actions in the PR and episode state. Existing rich approvals retain their current default and rollback semantics.
+
+The authenticated v1 rich event promises a complete forced-redacted preview of at most 16 KiB UTF-8.
```

```diff
-checks exact source digest, request and policy version;
+checks the canonical input fingerprint and its request/digest/action-kind/policy-version components;
```

```diff
-fixed approved HTTPS endpoint, no redirects.
+approval-specific fixed HTTPS endpoint validation at startup and immediately before I/O; redirect-rejecting urllib opener.
```

```diff
-including binding, source and four fields.
+including input_fingerprint, action_kind, policy_version, request/digest binding, source and four fields.
```

```diff
-provider_unavailable, timeout, provider_error, invalid_output, unsafe_output, binding_mismatch, source_unavailable, already_claimed.
+disabled, budget_exhausted, budget_unavailable, provider_unavailable, timeout, provider_error, invalid_output, unsafe_output, binding_mismatch, source_unavailable, already_claimed.
```

```diff
-version fixed, request UUID, SHA-256 digest, source, action/target/consequence/reason
+version fixed, request UUID, SHA-256 preview digest, canonical input_fingerprint, action_kind, policy_version, source, action/target/consequence/reason
```

```diff
-Request UUID, preview digest, action_kind from gateway allowlist, complete forced-redacted preview only.
+Request UUID, preview digest, action_kind from gateway allowlist, policy_version, canonical input_fingerprint, and complete forced-redacted preview only.
```

```diff
-Exact echoed request UUID and digest plus four required fields.
+Exact echoed request UUID, preview digest and input_fingerprint plus four required fields.
```

```diff
-Bind action_kind and policy version separately in server comparison.
+Bind all source components together in the canonical input fingerprint described below.
```

```diff
-The authorized detail flow first obtains the existing scoped approval.
+Canonical input identity (ADV-004): use the existing gateway `canonical_fingerprint`/`canonical_json_bytes` convention over exactly `{"approval_request_id":"<canonical UUID>","preview_digest":"sha256:<hex>","action_kind":"<allowlisted kind>","policy_version":"approval-explanation.v1"}`. Persist the resulting `canonical-json-sha256:v1:<64 lowercase hex>` as input_fingerprint inside the JSON projection, together with these exact components. The policy version changes whenever prompt, sanitizer or output-policy semantics change. Recompute from the current row before accepting cached copy, before sending, and before completion. CAS requires both the exact claimed fallback object and its input_fingerprint, plus matching current request UUID, action kind and exact preview bytes; no hash alone substitutes for tenant scope. Provider output must echo the expected fingerprint. Old JSON without the fingerprint or with mismatching components is invalid, becomes bound fallback, and does not trigger automatic regeneration. The additive migration leaves existing rows as `{}`; it performs no provider work.
+
+The authorized detail flow first obtains the existing scoped approval.
```

```diff
-The winner makes at most one provider call, then validates, reauthorizes, rechecks source and request identity, and conditionally replaces the same fallback object.
+The winner checks the dedicated enable gate and acquires the bounded tenant/global budgets below before any provider call. It makes at most one provider call, then validates, reauthorizes, recomputes the input fingerprint, and conditionally replaces the exact claimed fallback object. Disabled or exhausted paths retain deterministic fallback.
```

```diff
-no provider work on list/SSE/decision, no authority changes.
+no provider work on list/SSE/decision, aggregate budget exhaustion is fail-closed, no authority changes.
```

```diff
-Defaults are code constants unless the existing config convention needs a narrowly named opt-out; preserve default-on feature availability and provide a summary-specific off switch if operational rollback needs it.
+The dedicated `ALLIES_APPROVAL_SUMMARIES_ENABLED=false` default is mandatory until the named producer evidence passes. This summary-only gate does not disable rich approvals or alter their default-on availability. Use code constants for the bounds; no credentials-only enablement.
```

```diff
-Before sending, accept only the forced-redacted source proved in Phase 1;
+Transport (ADV-002): construct `urllib.request.build_opener` with an approval-specific `HTTPRedirectHandler` whose `redirect_request` refuses every redirect. Do not use plain `urlopen`, which follows redirects by default. Approval-specific settings validation requires the exact normalized URL `https://api.openai.com/v1/responses`: HTTPS, exact host/path, default port, no userinfo, query, fragment, alternate host or custom proxy endpoint. Reject an invalid configured endpoint at startup even while the gate is off, and revalidate immediately before request construction so runtime settings overrides cannot bypass it. Do not rely solely on waitlist settings checks. Treat all 3xx responses as provider_error with fallback; never issue a second request or forward Authorization to Location. Leave waitlist transport and policy unchanged.
+
+Aggregate provider budgets (ADV-001): reuse `auths.throttle.check_rate_limit` with authenticated workspace identity, approval-specific scope, limit 6/60 seconds and global_limit 30/global_period 60/global_scope for this operation. These are the existing anchored TTL buckets, not a claim of rolling-window precision. Tenant quota is checked first, so a hot tenant rejected by its own counter cannot consume global counter capacity. Counters are conservative and never refunded on failure. Also allow at most four provider calls across all Cloud processes and one per workspace. Use the existing shared Redis cache's atomic `add` for one HMAC-scoped tenant slot and four fixed global slot keys, with 7-second TTLs; probe at most four slots in a fingerprint-derived order. Keep slots until TTL expiry even after success, avoiding unsafe delete/release races and any lease-renewal framework. Start the six-second total I/O deadline when the first slot is acquired; recheck remaining time immediately before I/O and never start/continue after it. Rate budgets and both slots must succeed before transmission. Acquired slots or counts after later failure expire naturally and are not refunded. Disabled/nonshared LocMem deployment, missing Redis, cache error, no slot or exhausted quota returns stored fallback without a provider call, new disclosure or approval-state transition. In production the summary gate requires a configured shared atomic Redis cache; use a fake atomic cache for isolated tests and real Redis for cross-process proof. Per-tenant caps prevent one tenant occupying all slots; global saturation causes prompt fallback, not waiting or a promise of strict scheduling fairness. No queue, retry timer or polling is added.
+
+Before sending, accept only the forced-redacted source proved in Phase 1;
```

```diff
-5. Allowlisted forced-redacted input, strict bounded output, one-attempt budget, total deadline, fallback, source binding, tenant isolation and privacy-safe audit evidence all have failure tests.
+5. Allowlisted forced-redacted input, strict bounded output, one-attempt and aggregate tenant/global budgets, total deadline, fallback, canonical input fingerprint, default-off summary enablement, redirect rejection, tenant isolation and privacy-safe audit evidence all have failure tests.
```

```diff
-Equal previews across tenants never share state.
+Equal previews across tenants never share state. Test canonical fingerprint stability across dictionary ordering and invalidation when any one of request UUID, preview bytes/digest, action kind or policy version changes. Test migration `{}` defaults, old JSON without fingerprint, altered stored components and a source change during provider I/O; none can publish stale output.
```

```diff
-Existing delivery deadlines and late resolution behavior remain valid.
+Existing delivery deadlines and late resolution behavior remain valid. Test all 301/302/303/307/308 redirects with a second HTTP test server: one request reaches the first server, zero requests/credentials reach the second, and fallback is returned. Startup and runtime endpoint checks reject malicious or altered URLs independently of waitlist configuration. Test gate-off with valid credentials, gate-on with missing evidence recorded as a release blocker, invalid shared-cache configuration, per-tenant and global quota exhaustion, four occupied global slots, one occupied tenant slot, cache failure and process death. Prove at most four concurrent provider calls across workers, at most one for one tenant, and that a tenant rejected locally does not consume global quota. Expiry tests prove capacity recovers after seven seconds while no old call remains live. Budget/gate denial must not call the provider, reveal another tenant's data, add technical disclosure or change decision/status/expiry/delivery fields; existing authorized fallback/detail remains available.
```

```diff
-- `make test APP=allies/tests/test_foundry_gateway.py`.
+- `make test APP=allies/tests/test_foundry_gateway.py` and `make test APP=auths/tests/test_throttle.py`.
+- Summary tests use the existing shared Redis configuration for a cross-process budget proof; unavailable Redis is recorded as missing evidence, not a passing local-cache substitute.
```

```diff
-| GET incurs provider latency/cost. | Only one eligible scoped detail read claims a single <=6-second attempt; concurrent readers get fallback; no list generation. Revisit asynchronous generation only if measured demand requires it. |
+| GET incurs provider latency/cost. | One eligible detail read claims one <=6-second attempt; tenant/global rate counters and one/four concurrent slots bound aggregate work. Denial returns fallback. Revisit asynchronous generation only if measured demand requires it. |
```

```diff
-Rollback: disable only explanation generation and serve deterministic fields;
+Rollback: set `ALLIES_APPROVAL_SUMMARIES_ENABLED=false` and serve deterministic fields;
```



Better Docs edited the complete draft for direct wording and sentence clarity. Humanizer then checked the clean copy without changing contracts, limits, acceptance criteria or scope. All editing-check categories passed. The clean copy is `approval-language-contract.md`.

```diff
-Target users are people deciding whether their Ally may continue, Interface engineers implementing AT-029, and operators diagnosing failed explanation or delivery. Success means a scoped detail response carries understandable, request-bound copy and separate complete forced-redacted details; a committed choice is distinguishable from later execution confirmation.
+This plan serves people deciding whether their Ally may continue, Interface engineers implementing AT-029, and operators diagnosing failed explanation or delivery. A scoped detail response must carry understandable, request-bound copy and separate complete forced-redacted details. It must distinguish a committed choice from later execution confirmation.
```

```diff
-Use one new focused module because provider I/O and untrusted output need a clear boundary. Do not introduce a generic provider framework, new dependency, second queue, global cache, or service interface with one implementation.
+Keep provider I/O and untrusted-output validation together in one focused module. Do not introduce a generic provider framework, new dependency, second queue, global cache, or service interface with one implementation.
```

```diff
-| Process dies after claiming. | Durable fallback is the terminal generation outcome; do not retry automatically. This deliberately trades a missed summary for bounded cost and availability. |
+| Process dies after claiming. | Durable fallback is the terminal generation outcome; do not retry automatically. A missed summary leaves usable fallback and prevents another provider charge. |
```
