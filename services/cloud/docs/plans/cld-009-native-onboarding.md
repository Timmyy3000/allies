# CLD-009 Native onboarding plan

> Planning status: revised after adversarial review; simplicity review passed; fast-path self-approved for implementation.

## Feature overview

- Problem: `POST /api/v1/onboarding/attempts` always applies the browser Origin and CSRF contract. A valid mobile request has no browser cookies, Origin, Referer, or CSRF header, so staging rejects it before greeting generation.
- Target users: New Allies users on Android and iOS, plus existing web users whose onboarding security must remain unchanged.
- Source docs/specs: Nabu CLD-009, INT-008, the mobile onboarding implementation handoff, the Allies backend guide and decision log; this repository's work brief, `AGENTS.md`, `ENGINEERING_STYLE.md`, `README.md`, `Makefile`, CI and Enkii policies; and the Cloud code listed under Evidence.
- Success outcome: The existing mobile client receives the official attempt token and greeting from staging, can carry that attempt through native Google sign-in into authenticated Ally creation, and does so without weakening the web path or inventing a client-trusted identity.

### Primary decision

Keep the existing versioned route and request body. The controller selects one of two closed transport branches:

1. A request with any browser or session signal, including Origin, Referer, Cookie, `X-CSRFToken`, or Authorization, does not qualify for anonymous native fallback. Browser requests continue through the existing trusted-origin and double-submit CSRF checks. An Authorization-bearing create request is handled only as an authenticated native bearer after the existing session resolver validates its native client kind.
2. A public attempt request with none of those signals may enter the native branch only when `ALLIES_AUTH_NATIVE_ENABLED=true`. It must pass the existing Railway `X-Real-IP` parser and the existing cache-backed native throttle before provider or database work.

For authenticated create, a native bearer bypass is selected only when the
request has a syntactically valid `Authorization: Bearer` header, no access
cookie, no `Origin`, `Referer`, CSRF cookie, `X-CSRFToken`, or other browser
session signal, and the resolver validates `SessionClientKind.NATIVE`. A
browser-kind bearer, an invalid bearer, or any hybrid bearer/browser request
must not reach the native branch: it follows the browser/error path and cannot
bypass Origin/CSRF. This predicate is enforced at the HTTP boundary before
`create_ally`; the service still receives the authenticated user and exact
attempt token.

The native requester prefix is an abuse-control identity only. It must not become attempt ownership because mobile network addresses can change and can be shared. Native attempt ownership is possession of the high-entropy, short-lived attempt token, exact seed equality, one-time consumption, and the authenticated user's Workspace capability at create time. The browser path retains its additional CSRF-cookie binding.

### Why this is the smallest safe change

| Option | Security and compatibility | Cost | Decision |
| --- | --- | --- | --- |
| Branch the existing route by strict transport evidence | Preserves the current client and web route; browser-like or hybrid requests cannot fall through to native | Small Cloud-only change | Use |
| Add a dedicated native onboarding route | Makes transport explicit but adds no proof that the caller is a genuine app; requires Interface client and schema coordination | More files and rollout work | Reject |
| Bind ownership to `X-Real-IP` | Confuses rate-limit fairness with ownership and breaks on NAT or network changes | Fragile | Reject |
| Add an installation ID, app secret, attestation, or new binding model | A client-selected ID is not trusted; stronger attestation is outside CLD-009 | New protocol and state | Reject |

Ponytail full applies: reuse the current endpoint, session resolver, native identity parser, throttle, generation admission, attempt model, token digest, OpenAPI customizer, and error envelopes. Add no dependency, route, model table, migration, generic transport framework, or speculative device identity.

## User stories

1. As a mobile user, I want onboarding preview to work without browser state so that I can see my Ally's Cloud greeting.
2. As a mobile user, I want an invalid, throttled, disabled, or unavailable request to report a truthful recoverable error without exposing private details.
3. As a web user, I want onboarding to retain trusted-origin and CSRF protection.
4. As a signed-in mobile user, I want the attempt I started before sign-in to remain valid for one authenticated Ally create without using my network address as ownership.
5. As a deployment owner, I want one reversible feature gate and schema/device evidence before the ticket is closed.

## Scope

### In scope

- Add a strict native branch to `POST /api/v1/onboarding/attempts` while preserving the browser branch.
- Reuse `ALLIES_AUTH_NATIVE_ENABLED` as the rollout gate. It already defaults false and production startup validates Railway mode, shared cache, and complete native Google configuration.
- Extend the accepted native throttle vocabulary with an `onboarding` operation, defaulting to 5 requests per normalized requester prefix per 60 seconds and sharing the existing native global ceiling. The existing provider-generation budget and global concurrency remain a second, cost-specific admission layer.
- HMAC the normalized requester prefix before passing an identity to the generation admission cache. Never log or persist the raw address or normalized prefix.
- Support browser-bound and native capability-bound onboarding attempts without changing the database schema. A browser attempt remains bound to its CSRF cookie. A native attempt stores a digest derived from `"native:" + attempt_token`; the corresponding authenticated native create derives the same value.
- Allow `POST /api/v1/workspaces/{workspace_id}/allies` to use the existing validated native bearer path for consuming a native attempt. Browser creates still require Origin and CSRF.
- Preserve exact seed comparison, attempt TTL, one-time consumption, authenticated Workspace capability, idempotency, provider validation, generation admission, and safe response envelopes.
- Publish the transport, security, no-store, and stable error behavior in OpenAPI.
- Add focused tests, update the Railway runbook and deployment inventory comment, and require Cloud CI, Gitleaks, and all Enkii review lanes.
- Require staging schema, edge, Android, and iOS evidence before CLD-009 is closed.

### Out of scope

- Interface runtime or UI changes. The current mobile client already sends the accepted request body without browser credentials.
- A new native route, request field, client-generated identity, device attestation, app secret, or installation registry.
- Changes to AUTH-002 token, PKCE, Google provider, redirect, SecureStore, or session-family contracts.
- Chat and other native mutations. If their existing Origin handling blocks mobile later, file a separate bounded ticket rather than expanding CLD-009 silently.
- Provider prompt or greeting-content changes.
- Database schema changes, data backfills, or migration files.
- Live Railway configuration changes, deployment, EAS publication, device installation, commits, pushes, or PR creation during this planning run.

### Dependencies and assumptions

- Railway remains the only supported public staging ingress and overwrites `X-Real-IP`. The accepted AUTH-002 trust proof is reusable, but an owner must confirm its staging evidence before enablement.
- Redis remains the shared Django cache used by native throttles and generation admission.
- `ALLIES_AUTH_NATIVE_ENABLED` stays the single mobile rollout acknowledgement. Native onboarding and native Google continuation should not be independently enabled because the accepted flow requires both.
- The current attempt token has at least 256 bits of generated entropy, is stored only as a keyed digest, expires after the configured 1,800 seconds, and is never logged.
- The live staging OpenAPI fetched on 2026-09-04 returned HTTP 200 with SHA-256 `30c3552e5468abf88372d8cb243cb3d6c178b26c7495118befc6e0a060663856`. It contains the route and native auth operations but has no onboarding transport description or header parameters and uses generic error examples.
- Nabu reports an Android 1.0.3 preview build queued and no iOS preview artifact because Apple internal-distribution credentials are missing. That is an external acceptance dependency, not a reason to weaken Cloud proof.

## Contract and shape definitions

### Function and service shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `backend/allies/api/controllers.py` | local attempt transport selection | `(request) -> browser binding or native identity` | Native requires no browser/session signals, enabled flag, valid edge identity, and successful throttle | Browser binding bytes or native branch marker plus opaque generation identity | `403 origin_rejected`, `403 csrf_rejected`, `429 throttled`, or `503 onboarding_unavailable` |
| `backend/auths/api/common.py` | `check_native_rate_limit` | existing `(request, operation) -> str` | Add accepted `onboarding` operation through existing config; Railway requires exactly one valid `X-Real-IP` | Normalized `/24` or `/64` prefix in memory | Existing helper HMACs cache keys; `ThrottleExceeded`, `ThrottleUnavailable`, or `NativeIdentityUnavailable` |
| `backend/allies/services/onboarding.py` | `begin_onboarding` | existing arguments with `browser_binding: bytes | None` | `bytes` must be non-empty for browser; `None` means native capability binding | Existing `OnboardingStart` | Generates once, stores attempt, propagates throttle separately from provider/admission unavailability |
| `backend/allies/services/creation.py` | `create_ally` | existing arguments with `browser_binding: bytes | None` | `None` is accepted only from the closed native-create predicate; exact attempt token and seed still required | Existing `AllyCreationResult` | Compute the keyed attempt digest before idempotency lookup; include it in the fingerprint; preserve transaction, one-time consume, conversation handoff, and safe failures |

No new public helper module or transport abstraction is planned. A short private binding derivation in `onboarding.py` may be reused by begin and create; it must be the only new helper if duplication would otherwise risk a mismatch.

### API and transport contracts

| Consumer | Method and path | Authentication and authorization | Request schema | Success | Stable failures and retry |
| --- | --- | --- | --- | --- | --- |
| Web | `POST /api/v1/onboarding/attempts` | Public, but exact trusted Origin or Referer plus matching CSRF cookie/header | Existing `OnboardingAttemptRequest` | `200` existing token and greeting envelope; `Cache-Control: no-store` | `403 origin_rejected`, `403 csrf_rejected`, `422 validation_error`, `429 throttled`, `503 onboarding_unavailable`; retry 429/503 after backoff |
| Native | `POST /api/v1/onboarding/attempts` | Public; no Origin, Referer, Cookie, `X-CSRFToken`, or Authorization; feature enabled; server-authoritative requester throttle | Same existing schema | Same `200` envelope and no-store header | `422 validation_error`, `429 throttled`, `503 onboarding_unavailable`; never emulate browser state |
| Web create | `POST /api/v1/workspaces/{workspace_id}/allies` | Existing browser session, Workspace write capability, Origin, CSRF, Idempotency-Key | Existing `CreateAllyRequest` | Existing `201` or `202` envelope | Existing errors and idempotency behavior |
| Native create | Same create route | Existing native bearer resolver with `SessionClientKind.NATIVE`; no Origin, Referer, access cookie, CSRF cookie/header, or hybrid signal; native feature enabled; Workspace write capability | Same existing schema and Idempotency-Key | Same `201` or `202` envelope | `401 session_invalid`, `404 ally_unavailable`, `409 idempotency_conflict`, `422 onboarding_invalid`; network retry reuses exact token, body, and key |

Representative request, unchanged:

```json
{
  "name": "Diagnostic Ally",
  "job": "General helper",
  "personality": "Helpful and concise",
  "appearance": {
    "catalog_version": "ghosty",
    "key": "ff5800"
  }
}
```

Representative success, unchanged:

```json
{
  "status": "success",
  "message": "Onboarding started",
  "data": {
    "attempt_token": "<opaque-one-time-attempt>",
    "greeting": "Hi, I can help with that. What should we start with?"
  }
}
```

OpenAPI must mark the attempt operation public, describe both branches, list optional browser headers without implying they belong on native requests, publish status-specific safe error examples, and document `Cache-Control: no-store`. The create operation must document browser-cookie plus CSRF or native-bearer alternatives without claiming anonymous create access.

### Data shapes and invariants

#### Database models

No schema change. `OnboardingAttempt` keeps its current fields and indexes. The existing `browser_binding_digest` column is retained to avoid a rename-only migration. Its enforced meaning becomes a transport binding digest:

- Browser: `HMAC(CSRF cookie)`.
- Native: `HMAC("native:" + attempt token)`.

The model docstring must stop claiming every attempt is browser-bound. The raw token, CSRF value, requester address, normalized prefix, and native binding material must not be persisted or logged.

#### Enums

Not applicable. Transport is resolved at the HTTP boundary and does not need a persisted enum.

#### API request schemas

No field changes. `OnboardingAttemptRequest` and `CreateAllyRequest` retain their current limits and `extra="forbid"` behavior.

#### API response schemas

No body changes. `OnboardingAttemptResponse` retains `attempt_token` and `greeting`.

#### Temporary and internal shapes

| Shape | Lifetime | Invariant |
| --- | --- | --- |
| Native requester prefix | One request, memory only | Railway edge supplied, one IP, normalized `/24` or `/64`, never ownership |
| Native throttle key | Configured cache window | Existing helper performs keyed HMAC; onboarding scope and shared native global ceiling |
| Generation admission identity | One generation budget window | Derived opaque HMAC, not a raw network prefix |
| Native attempt binding | Attempt TTL | Derived from the secret attempt token with a domain prefix; only keyed digest persists |

#### Idempotency identity

- Compute `attempt_token_digest = digest_value(onboarding_attempt)` before the
  existing idempotency lookup. The digest is keyed and is the only attempt
  material included in the fingerprint; the raw token is never persisted or
  logged.
- The content fingerprint covers the normalized seed, reply, and
  `attempt_token_digest`. An exact retry with the same workspace, user,
  idempotency key, token, and body replays the original result. A changed token
  (even one with valid length), seed, reply, or body conflicts before any
  attempt is consumed and remains rejected after consumption.
- During a rolling deploy, a pre-existing operation with the legacy seed/reply
  fingerprint remains replayable only when its linked consumed attempt matches
  the submitted token digest and transport binding. New operations always use
  the attempt-aware fingerprint; a wrong token or binding conflicts.
- Do not use the requester prefix, bearer value, CSRF value, or any
  client-generated identity in the operation identity.

#### Service primitives

No new public service primitive. `begin_onboarding` and `create_ally` remain the owners of attempt creation and consumption.

### Frontend interaction shapes

No Interface source change is planned. Sequencing remains:

`mobile seed -> public native attempt -> Cloud token and greeting -> user reply -> native Google sign-in if needed -> authenticated native create with the same token, seed, body, and idempotency key -> first conversation`

Mobile must keep truthful loading, retry, unavailable, and throttled states. It must not add Origin, Referer, cookies, CSRF, or a client identity to work around Cloud.

## Exact changed files

| File | Planned change |
| --- | --- |
| `backend/allies/api/controllers.py` | Closed browser/native selection, native gate/throttle/error mapping, no-store response, and native bearer create path |
| `backend/allies/services/onboarding.py` | Optional browser binding, native capability binding, opaque generation identity helper, and truthful throttle propagation |
| `backend/allies/services/creation.py` | Derive and verify native capability binding when the validated controller passes no browser binding |
| `backend/allies/models.py` | Correct the model description only; no field or migration change |
| `backend/auths/config.py` | Add `onboarding` to the existing closed native rate-limit operation map with default 5 |
| `backend/config/settings.py` | Read and production-validate `ALLIES_AUTH_NATIVE_ONBOARDING_LIMIT` with the existing native limits |
| `.env.deploy.example` | Document the onboarding limit and that the existing native gate covers auth plus onboarding |
| `backend/config/openapi.py` | Onboarding transport description, parameters, no-store metadata, safe error examples, and dual create security documentation |
| `backend/allies/tests/test_api.py` | Native/browser HTTP, hybrid rejection, create continuation, errors, and no-store regression cases |
| `backend/allies/tests/test_services.py` | Browser/native binding, cross-transport rejection, seed tampering, one-time consume, keyed attempt fingerprint, and throttle/provider separation |
| `backend/allies/tests/test_concurrency.py` | PostgreSQL simultaneous native creates; one-time consumption plus same-key replay and different-key conflict outcomes |
| `backend/auths/tests/test_native_security.py` | Onboarding operation scope, limit, normalized identity, shared global ceiling, and failure behavior |
| `backend/config/tests/test_api_contract.py` | OpenAPI transport, security, headers, no-store, and status-specific examples |
| `backend/config/tests/test_settings.py` | Native onboarding limit default and fail-closed production validation |
| `docs/operations/railway-staging.md` | Reuse of the accepted edge trust proof, rollout checks, sanitized evidence, and rollback |

No other production file should change unless implementation evidence proves this list incomplete. In that case, stop and revise the plan before expanding scope.

## Phases

### Phase 1 - Implement the transport and ownership boundary

- Goal: Make the current public attempt and authenticated create sequence work for native without weakening web.
- Work items:
  - Add strict browser/session-signal classification at the attempt controller.
  - Keep browser Origin and CSRF checks byte-for-byte equivalent in behavior.
  - Gate the native branch with `ALLIES_AUTH_NATIVE_ENABLED`.
  - Run `check_native_rate_limit(request, "onboarding")` before provider or database work; map identity/cache failure to `503 onboarding_unavailable` and exhaustion to `429 throttled`.
  - Convert the returned prefix to an opaque keyed generation identity before calling `begin_onboarding`.
  - Bind native attempts to the secret token capability, while browser attempts stay CSRF-bound.
  - Add an explicit native-create predicate before `_require_origin`: only a bearer with no Origin, Referer, access/CSRF cookie, `X-CSRFToken`, or other browser/session signal qualifies; resolve it with `SessionClientKind.NATIVE`, then require Workspace capability and verify the matching native token binding. Browser-kind bearers and every hybrid combination remain on the browser/error path.
  - Compute the keyed attempt-token digest before the existing idempotency lookup and include it in the content fingerprint; preserve exact-token/body/key replay and reject altered-token replay before and after consumption.
  - Preserve exception classes through `begin_onboarding`: requester throttle and `waitlist.exceptions.Throttled` from generation map to `429 throttled`; `NativeIdentityUnavailable`, cache/admission failures, provider unavailable/unknown, and validation failures map to their existing truthful responses without provider/database work after a pre-admission failure.
  - Reject hybrid and cross-transport combinations. Do not fall back from a failed browser check to native.
- Impacted files/systems: controllers, onboarding/create services, model description, native throttle config, tests.
- Exit criteria: Focused service and API tests prove native success and continuation, browser success and rejection, cross-transport rejection, stable errors, idempotency, and no raw identity/token persistence.

### Phase 2 - Publish and verify the contract

- Goal: Make generated OpenAPI describe the behavior that code implements.
- Work items:
  - Add the attempt transport matrix, public security declaration, browser header guidance, no-store header, and safe status-specific examples.
  - Document the authenticated create transport alternatives without marking create anonymous.
  - Extend settings and deployment inventory for the bounded native onboarding limit while reusing the existing feature gate.
  - Update the Railway runbook with enablement evidence and rollback.
  - Run targeted and full Cloud validation, then require CI, Gitleaks, and Enkii general, code, security, and policy lanes to clear all actionable findings.
- Impacted files/systems: settings, deployment example, OpenAPI customizer/tests, operations guide, CI review evidence.
- Exit criteria: Local schema tests pass; the diff contains no route/body/dependency/migration change; all required review lanes are complete or an exact external blocker is recorded.

### Phase 3 - Promote Cloud, synchronize Interface, and prove devices

- Goal: Close the gap between merged source, staging schema, edge behavior, and the installed mobile app.
- Work items:
  - After plan approval, create and monitor the Cloud PR targeting `dev`; do not merge it in this task. PR approval, merge authorization, staging promotion, and feature-flag/configuration authority are separate owner-controlled gates and are not implied by plan approval or PR readiness.
  - Only an explicitly authorized owner may merge or promote the validated revision to `staging`; after such authorization, confirm Railway web, worker, and beat report the same commit.
  - Confirm the staging owner has accepted the `X-Real-IP` anti-spoof and shared-cache proof before setting or retaining `ALLIES_AUTH_NATIVE_ENABLED=true`.
  - Fetch staging OpenAPI, record its SHA-256, and assert the attempt operation contains the reviewed transport description, error examples, security, and no-store header.
  - In a separate Interface-owned change only if the fetched schema bytes changed, refresh the pinned snapshot/metadata, run `bun run cloud:generate` and `bun run cloud:check`, and confirm no runtime client method change is needed.
  - Run Android proof first with a compatible 1.0.3 development/preview build. Then run the same proof on iOS after Apple internal-distribution credentials produce a real preview build. Expo Go is not evidence.
  - Capture sanitized evidence for no-browser-header 200, token/greeting keys, preview display, reply continuation, Google system-browser sign-in, native create, and preserved web onboarding. Redact attempt/session tokens and private provider details.
- Impacted systems: Railway staging, live OpenAPI, Interface contract snapshot, Android and iOS builds.
- Exit criteria: Both device platforms pass the reviewed staging flow, browser regression proof passes, schema and deployed behavior agree, and evidence names exact Cloud and Interface revisions. If iOS credentials remain unavailable, Cloud code may be reviewable but CLD-009 stays externally blocked rather than claiming full acceptance.

## Acceptance criteria

1. A native staging attempt with no Origin, Referer, Cookie, CSRF, or Authorization returns 200 with `attempt_token` and `greeting`, plus `Cache-Control: no-store`.
2. A browser or hybrid request never falls through to native. Trusted browser Origin plus valid CSRF succeeds; untrusted/missing origin or invalid CSRF retains the existing 403 codes.
3. Native admission uses only the accepted server-authoritative Railway identity, the onboarding requester limit, shared native ceiling, and existing generation controls. Missing/malformed identity or cache failure performs no provider/database work and returns 503.
4. Requester or generation exhaustion returns 429 `throttled`; provider and admission unavailability return 503 `onboarding_unavailable`; invalid input returns 422 `validation_error`.
5. A native attempt survives Google continuation and is consumed once by an authenticated native bearer with Workspace write capability, exact seed, and stable idempotency key. The keyed attempt-token digest is part of the content fingerprint, so a different valid-length token conflicts before and after consumption while an exact token/body/key retry replays.
6. Browser/native cross-consumption, token/seed tampering, expired tokens, repeated consumption, foreign Workspace access, and changed-content idempotency are rejected without disclosing whether an attempt exists.
7. No raw attempt token, CSRF value, address, normalized prefix, Authorization value, or provider detail enters logs, database fields, OpenAPI examples, or captured evidence.
8. OpenAPI documents the unchanged request/response body, both transport branches, no-store behavior, authentication alternatives for create, and every stable error code.
9. No new dependency, route, model table, migration, client request field, or Interface runtime change is introduced.
10. Targeted tests, `make check`, `make lint`, Ruff format check, the complete test suite, AUTH coverage, CI PostgreSQL job, Gitleaks, and Enkii general/code/security/policy reviews pass.
11. Staging OpenAPI and behavior match the promoted commit, and Android plus iOS real-build proof is recorded. External inability to deploy or sign iOS keeps acceptance open.

## Backend considerations

### Query optimization plan

- The attempt path retains one insert after provider success. Native identity and throttles are cache operations and add no database query.
- The create path retains the indexed token-digest lookup under `select_for_update`, existing Workspace capability lookup, and existing idempotency lookup. Compute the keyed attempt-token digest before that lookup and include it with normalized seed and reply in the content fingerprint; this adds no query or persisted raw secret.
- Expected query-count change: zero for browser; zero database queries before native throttle/provider admission; no new relation access or collection scan.
- Measurement: keep focused tests asserting no attempt row on rejected/throttled/unavailable requests. No production query instrumentation is justified for this change.

### N+1 prevention

Not applicable. The changed operations handle one request and one attempt. They do not iterate over related records.

### Migration plan

No migration. Keep the existing column and update only its documented invariant. `make check` must prove `makemigrations --check --dry-run` is clean. If implementation requires a model field or enum, stop and return to planning.

### Detailed unit test cases

- Happy path: browser attempt; native attempt with valid Railway identity; native attempt followed by native bearer create; exact replay of create.
- Validation: empty/overlong/extra seed fields; malformed native IP; comma-separated IP; browser marker without valid browser security; bearer on public attempt; browser-kind bearer and every bearer/browser hybrid on create.
- Security: forged client IDs and forwarded headers do not influence identity; raw identity/token absent from logs and persisted values; browser/native cross-consumption fails; foreign Workspace remains non-disclosing.
- Abuse controls: native onboarding limit and shared global ceiling; existing generation budget/concurrency; cache unavailable; no provider or row write after pre-admission failure.
- Failures: provider unavailable/unknown, invalid provider output, generation admission unavailable, requester throttle, generation throttle, feature disabled, expired or consumed attempt; assert requester/generation throttle is 429 and identity/cache/provider/admission failure is 503.
- Idempotency: altered valid-length token conflicts before consumption and after consumption; exact token/body/key replays; same-key concurrent native creates produce one Ally, while different keys produce a deterministic conflict/one-time-consumption outcome.
- PostgreSQL concurrency: extend `backend/allies/tests/test_concurrency.py` with simultaneous native creates and explicit same-key/different-key assertions under the existing PostgreSQL marker.
- Compatibility: current browser Origin/CSRF tests, session-kind enforcement, exact seed and idempotency tests, OpenAPI examples, and no-store metadata.

## Frontend considerations

### Data path

- User action: mobile enters preview after name, appearance, job, and personality.
- Client: existing `beginOnboarding` request sends JSON with credentials omitted.
- Backend: existing attempt route selects native, throttles, generates, validates, stores, and returns token/greeting.
- UI: existing mobile model displays greeting and retains token.
- Continuation: reply is retained; Google sign-in returns a native bearer; existing create request sends the same token, seed, reply, and idempotency key.
- Errors: 422 is correctable input, 429 is backoff, 503 is unavailable/retry, 403 on mobile indicates an unexpected browser/hybrid request and must not be relabeled as a network error.

### State management considerations

No change. The existing mobile onboarding state and encrypted pending command remain authoritative on Interface. Cloud must not require Interface to add browser state or a device identity.

### Mobile sequencing

1. Land and validate Cloud source first.
2. Promote the exact Cloud revision and verify live OpenAPI before refreshing the Interface snapshot.
3. Regenerate only the existing Interface contract artifacts; do not hand-edit generated types or change runtime code unless generation proves a real contract delta.
4. Run Android real-build proof as soon as the queued/finished 1.0.3 artifact is available.
5. Provision Apple signing credentials and create an iOS preview build, then repeat the same proof before ticket closure.

## Test plan

- Focused API/services: `make test APP="allies/tests/test_api.py allies/tests/test_services.py"`
- Native trust and settings: `make test APP="auths/tests/test_native_security.py config/tests/test_settings.py"`
- OpenAPI: `make test APP=config/tests/test_api_contract.py`
- PostgreSQL concurrency: `make test APP=allies/tests/test_concurrency.py` with PostgreSQL available; the new native race test must be covered by the CI PostgreSQL job.
- Repository checks: `make check`, `make lint`, then `cd backend && uv run ruff format --check .`
- Full suite: `make test`
- CI parity: `cd backend && uv lock --check`; `uv run python manage.py migrate --noinput`; `uv run python manage.py migrate --check`; `uv run pytest --cov=auths --cov=workspaces --cov-fail-under=90`; `uv run pytest -m postgresql` with PostgreSQL.
- Diff hygiene: `git diff --check`; inspect `git status --short`; confirm no migration, lockfile, or unrelated file drift.
- PR gates: CI `Django checks and tests`, `PostgreSQL UUID schema and concurrency`, Gitleaks, and Enkii general/code/security/policy. Resolve every actionable P0-P2 finding or record an authorized policy exception with owner and revisit condition.
- Staging proof: fetch `/api/v1/openapi.json`; record hash and operation fields; issue a controlled no-browser-state request through the public edge; verify browser request separately; record only sanitized status, code, field names, revisions, and timestamps.
- Device proof: real Android and iOS development/preview builds, system browser Google flow, no Expo Go, no browser emulation, and no secret-bearing screenshots/logs.

## Risks and mitigations

| Risk | Mitigation | Rollback or fallback |
| --- | --- | --- |
| Absence of browser signals is treated as native by scripts or bots | This route is intentionally public; require the rollout flag, accepted edge identity, per-prefix and global native throttle, and provider generation controls | Set `ALLIES_AUTH_NATIVE_ENABLED=false`; browser stays available |
| A hybrid request bypasses browser CSRF | Any browser/session signal selects or rejects the browser path; never retry a failed browser check as native | Disable native flag and revert the controller branch |
| IP churn or shared NAT breaks ownership | Use the prefix only for rate limits; use the secret attempt capability and authenticated Workspace at create | Token expires naturally; do not bind accounts to network identity |
| A stolen attempt token is consumed by another account | Keep 256-bit token entropy, no-store response, keyed digests, 30-minute TTL, exact seed, one-time consume, and non-disclosing errors | Disable native onboarding; allow outstanding tokens to expire or run existing bounded cleanup |
| Native and generation throttles overlap | Keep separate scopes because one protects the public native surface and shared native ceiling while the other protects provider cost/concurrency; test both classifications | Tune the existing onboarding limit through deployment config after measured evidence |
| Shared native global ceiling couples onboarding and auth | Per-prefix limit and low onboarding default bound one caller; monitor 429s during staged proof | Disable native onboarding with the shared gate; split gates only if measured operational evidence justifies it |
| OpenAPI source, Interface snapshot, and staging drift | Promote one SHA, fetch live schema, record hash, then regenerate Interface artifacts | Do not publish the mobile acceptance claim until all revisions match |
| Feature-gate rollback also disables native sign-in | The onboarding journey requires native sign-in, so partial enablement is not useful in this slice | Browser onboarding/account access remains; re-enable only after the defect is fixed |
| Android or iOS proof cannot run | Keep Cloud code review separate from ticket acceptance and record the exact external blocker | Android first; iOS remains required after signing credentials exist |

## Rollback

1. Set `ALLIES_AUTH_NATIVE_ENABLED=false` through the authorized Railway configuration workflow and redeploy the exact staging revision. This blocks new native attempts and native create continuation while leaving browser onboarding unchanged.
2. Verify browser attempt/create and live OpenAPI after rollback. The schema may still describe a disabled capability, so the operation description must state the feature gate.
3. Existing unconsumed attempts contain no account ownership and expire through the existing TTL/cleanup. Do not delete rows manually.
4. If configuration rollback is insufficient, revert the focused Cloud commit and promote through the normal dev-to-staging workflow. No database rollback exists because there is no migration.

## External decisions and proof still required

- Deployment/security owner confirmation that Railway's public edge overwrites forged `X-Real-IP`, no alternate public ingress exists, and both web workers use the shared Redis cache. Without this, keep native disabled.
- PR approval, merge authorization, staging promotion, and feature-flag change are separate owner-controlled decisions. Plan approval and PR readiness do not grant any of them; this task leaves the PR unmerged.
- Interface-owned schema refresh after live Cloud publication. The current Nabu handoff records a pre-existing snapshot metadata mismatch that must be reconciled rather than hidden.
- Apple signing credentials and an iOS preview build. Android evidence does not erase this accepted platform requirement.

The reviewed code-design mechanics are resolved above: native create requires
the closed native-session/no-browser-signal predicate, the keyed attempt digest
is part of idempotency identity, and throttle classes retain distinct mappings.
The remaining open items are execution authorities and external acceptance
dependencies, not permission to merge or enable staging.

## Adversarial review disposition

- Blocker: resolved by the closed native-create predicate and negative hybrid/session-kind tests.
- Attempt replay major: resolved by including the keyed attempt-token digest in the content fingerprint and testing altered-token replay before and after consumption.
- Error-truth major: resolved by preserving requester/generation `Throttled` as `429` and mapping identity/cache/provider/admission failures to `503`, with separate tests.
- Concurrency major: resolved by extending the PostgreSQL concurrency suite with native same-key and different-key races.
- Authority major: resolved by separating plan/PR approval, merge, staging promotion, and feature-gate authority; the PR remains unmerged.
- HTML truth minor: resolved by synchronizing the revised status and boundary mechanics in the HTML artifact.

## Evidence inspected

- `E:\Users\Oluwatimilehin\Documents\Programming\helpers\allies-cloud\.forest\worktrees\fix\cld-009-native-onboarding\.agent\cld-009-native-onboarding.md`
- Repository `AGENTS.md`, `ENGINEERING_STYLE.md`, `README.md`, `Makefile`, `docs/templates/PLAN_TEMPLATE.md`, `.enkii/policy-review.md`, `.github/workflows/ci.yml`, `.github/workflows/enkii-review.yml`, and `.github/workflows/secret-scan.yml`.
- Cloud onboarding controllers, schemas, model, services, tests, native auth identity/throttle/session code, settings, middleware, OpenAPI customizer/tests, deployment example, and Railway staging runbook.
- Nabu `projects/allies/index.md`, CLD-009, INT-008, mobile onboarding implementation, backend development guide, and engineering decision log.
- Live staging OpenAPI fetched 2026-09-04, HTTP 200, SHA-256 `30c3552e5468abf88372d8cb243cb3d6c178b26c7495118befc6e0a060663856`.
- Current Lavish `plan`, `diagram`, `table`, `comparison`, and `code` playbooks, plus `https://vercel.com/design.md` as visual guidance only.
