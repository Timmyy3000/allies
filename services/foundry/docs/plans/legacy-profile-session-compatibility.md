# Legacy profile-session compatibility hotfix

## Scope

Restore normal replies for existing Allies profiles that began failing with HTTP 403 after profile sandboxing reached beta. Preserve profile isolation, stable Hermes session keys, conversation history, and rich approvals. Do not migrate or rewrite persisted sessions.

## Approach

1. Correct the pinned Hermes overlay so the child middleware sets and reliably resets `_api_request_profile` from its validated immutable sandbox profile after the `/p/{profile}` prefix is stripped.
2. Let the child ContextVar fix rich-approval stream admission. Use one narrow profile matcher only where bootstrap and approval-control handlers compare a route profile: prefixed parent routes must match, while an unprefixed authenticated sandbox child must match its immutable child identity.
3. Treat the authenticated, forwarded-marker-validated Unix-socket child as an allowed bootstrap origin while retaining the existing loopback-only rule for parent TCP requests.
4. Extend the approval smoke to reproduce the real parent-to-child route shape through middleware and prove pending approval, status lookup, decision delivery, and same-stream completion through unprefixed child routes. Keep negative mismatch, missing/forged forwarding marker, and authentication checks.
5. Cover ContextVar cleanup after normal return, handler error, cancellation, and a following request so profile identity cannot leak between tasks or requests.

## Affected surfaces

- `runtime/hermes-image/patches/profile-sandbox.patch`
- `runtime/hermes-image/patches/first-turn-transcript-bootstrap.patch` behavior as composed with the final sandbox overlay
- `runtime/hermes-image/allies_profile_sandbox.py` only if a shared narrow profile-match helper is needed
- `runtime/hermes-image/smoke_approval_endpoint.py` or an equivalent focused image smoke
- Pinned Hermes image build and promotion; no Cloud, Interface, database, or runtime protocol changes

## Acceptance

- Existing profile sessions no longer receive `rich_approval_scope_required` solely because the child request path is unprefixed.
- Parent authentication and the private forwarded-marker boundary remain mandatory.
- Child/profile mismatches, default profile scope, unscoped ingress, and wrong credentials still fail closed.
- Stable session keys and existing histories are unchanged.
- Py and Shaka can answer in their existing conversations after rollout.

## Validation

- Run the focused Hermes approval and profile-sandbox tests/smokes, including pending → status → decision → same-stream completion through stripped child routes.
- Verify stripped child bootstrap and ContextVar reset on success, exception, cancellation, and the next request.
- Run `uvx --from pytest==8.4.2 --with PyYAML==6.0.3 pytest runtime/hermes-image/provider/tests/test_provider.py runtime/hermes-image/tests -q` and `git diff --check`.
- Verify every source overlay applies cleanly to the pinned Hermes commit.
- Run changed-file formatting/lint and repository diff checks.
- Build the Hermes image and run the relevant release smoke when Docker is available.
- Require independent adversarial/correctness review and Ponytail simplicity review before PR readiness.
- After verified image adoption, test both existing affected conversations (Py and Shaka) and confirm completed responses rather than only healthy containers.

## Risks

- Over-broad child trust could weaken profile authorization. Mitigation: accept only the immutable sandbox-child profile already established by the authenticated parent and private Unix-socket forwarding boundary.
- A patch may pass unit tests but fail after overlay composition. Mitigation: apply/build the complete ordered image patches and run the final-image smoke.
- A healthy deployment may leave existing machines on an old digest. Mitigation: verify image adoption before the browser retest.

## Unresolved decisions

None. The hotfix changes compatibility at the existing profile boundary and does not add a new public contract.

## Rollback

Redeploy the last successful pre-sandbox Hermes image, `ghcr.io/alliesai/allies-hermes@sha256:0e1ac2460d004c95a79720fbf342dbed7cd936b87f57691475e9cf7a81f7fe2a` (staging release run `35116152641`, Foundry `5557d42`), verify every affected Fly machine adopts it, then retest Py and Shaka. This emergency rollback restores replies but also restores the earlier weaker workspace boundary, so it is temporary and must be replaced by this corrected image. No database rollback is needed because the hotfix performs no persistence migration or session rewrite. The currently affected image is `ghcr.io/alliesai/allies-hermes@sha256:d40f0e4a1e0b1cca84d20e1a9645d5c0ff6a5b3d45b05aff824d79e0167aba8c` and is not an acceptable fallback.
