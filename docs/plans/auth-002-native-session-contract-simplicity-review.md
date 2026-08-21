# Simplicity Review

## Verdict

Simplification recommended. The revised plan retains the accepted security
controls, but one Phase 4 exit gate requires INT-008 work before AUTH-002 can
unblock INT-008. Remove that circular gate and make the stated consumer
contract proof the AUTH-002 handoff evidence.

## Findings

| Severity | Classification | Plan area | Evidence | Recommendation | Preserved outcome |
| --- | --- | --- | --- | --- | --- |
| Blocker | Remove/Defer | Phase 4 mobile smoke proof | The plan excludes SecureStore, mobile screens, and INT-008 implementation, and says the Cloud contract lands before INT-008 starts. Yet Phase 4 requires iOS and Android development-build proof for callback, restore, refresh, logout, and revocation before INT-008 becomes ready. The current mobile provider is only `unavailable:native-session-contract-pending`. Nabu `EPIC-00` and `INT-008` also sequence mobile implementation after the published AUTH-002 contract. | Move the device lifecycle proof to INT-008 acceptance. Keep AUTH-002's Interface-owned pinned-schema compilation, request-capture, bearer-allowlist, and error-state tests as its consumer gate. Keep only deployment-owned app-link and Google-registration verification in AUTH-002. | A published Cloud contract remains executable and safe before mobile product work begins. |
| Important change | Simplify | Railway requester identity and cache key | The plan specifies a pre-HMACed requester value and an exact Redis key format. The existing `auths.throttle.check_rate_limit` already HMACs its `identity` and owns the actual key format. The proposed `ALLIES_AUTH_NATIVE_RAILWAY_REAL_IP_PROVEN` setting is an operational attestation, not runtime evidence that Railway overwrites `X-Real-IP`; Railway documents the header but not that overwrite property. | Use the existing helper once: pass the normalized prefix as its non-secret identity and make its generated key the only key contract. Keep staged forged-header, multi-worker, and cache-outage tests. Record their signed-off result in deployment evidence; if the setting remains, name it only as an explicit rollout acknowledgement, not proof. | Shared, privacy-safe, fail-closed native rate limits without a parallel key mechanism or false runtime proof. |
| Important change | Simplify | Interface five-method handoff | The table defines four new native methods. Its fifth row is a group of existing account, profile, avatar, and Workspace methods. The current `@allies/cloud-client` already exposes that account surface and one generic `prepareRequest` seam. Calling this five methods makes the compile requirement ambiguous and risks a duplicate account wrapper. | Define the handoff as four new native-session methods plus the existing named account methods used through a native bearer preparer. Change the test requirement to compile those four methods and capture the existing-account allowlist separately. Add a fifth method only if Interface identifies a new consumer need. | The full bearer allowlist and all error-to-state behavior remain tested without inventing an adapter API. |
| Observation | Remove/Defer | Forward-upgrade proof | The required proof is one migration from `auths.0002` with a live browser refresh row. The plan also requires migrating to the already-reached leaf a second time inside the same `MigrationExecutor` test. CI already runs `migrate --check`, and a second no-op migration does not add compatibility evidence. | Run the old-to-new migration once on SQLite and PostgreSQL, assert `client_kind=browser`, and rotate the seeded refresh token. Restore the graph in `finally`; leave repeat-application coverage to the normal migration checks. | Direct proof that existing browser sessions survive the additive schema change. |
| Observation | Simplify | Markdown/HTML phase parity | The HTML correctly labels itself condensed and now lists all five Markdown phases. However, its Phase 1 exit claims PostgreSQL row-lock completion and refresh-winner proof, while Markdown puts those tests in Phase 2. Its Phase 4 wording also repeats the circular device-lifecycle gate. | Keep the condensed HTML. Align Phase 1's exit with migrations, callback isolation, and cleanup only; put race proof in Phase 2. After deferring device lifecycle proof to INT-008, remove it from both Phase 4 artifacts. | Reviewers retain an accurate visual map without a second source of sequencing truth. |

## Protected Complexity

- Keep separate native transaction and exchange-code tables. Reusing the
  browser `AuthFlow` would add nullable cookie and CSRF branches to a public
  client flow with different replay and callback semantics.
- Keep the five-state callback model, claim lease, protected cleanup order,
  and PostgreSQL race tests. These directly resolve the accepted callback and
  cleanup finding while keeping provider I/O outside database locks.
- Keep `SessionFamily.client_kind` and one shared JWT/refresh engine. The
  current session service already validates a family from every JWT, so this is
  the narrowest transport-separation control and avoids a second token system.
- Keep the exact callback selection in `ProviderFlow` and separate browser and
  native callback settings. The current Google adapter overrides a flow value
  with the one browser setting during both authorization and token exchange.

## Plan Feedback For Revision

- Make the AUTH-002 handoff end with Cloud staging publication and the
  Interface contract-only test. Make the later INT-008 plan own device session
  lifecycle smoke tests.
- Replace the custom native throttle key description with the existing throttle
  helper's one HMAC transform. Do not describe deployment attestation as a
  runtime trust proof.
- Correct the four-new-method versus existing-account-surface wording and its
  acceptance criterion.
- Remove the duplicate forward-migration execution and synchronize the two
  phase summaries.

## Residual Risk

The plan remains intentionally blocked until owners accept exact return URIs,
callback registrations, rate values, and the Railway edge trust evidence.
These are external decisions, not fields or values the plan should invent.

## Confidence

High - The review used the AUTH-002 and INT-008 Nabu records, revised Markdown
and HTML artifacts, adversarial review, Cloud auth/session code, Makefile and
CI, the Railway documentation, and the current Interface mobile and
cloud-client boundaries. The harness exposes no worker-dispatch tool, so this
is the simplicity skill's current-session fallback rather than a fresh-worker
review.
