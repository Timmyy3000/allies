# CLD-012 independent Sol code review — revision 14

Date: 2026-09-09
Verdict: ACCEPT

## Scope

Read-only follow-up review of the revision-14 Cloud and Foundry contract
artifacts and their consumer tests. The review covered the revision-13
schedule, lifecycle/action-attempt correction, bounded feasibility fixes, the
Foundry service-identity alignment raised by hosted review, the complete
history-canary matrix, and bounded cleanup after uncertain Docker side effects.

## Finding disposition

No actionable P0, P1, or P2 correctness, security, or policy findings remain.
Revision 14 aligns every routine Foundry envelope with the existing v1
`foundry-service` identity literal, recomputes all four affected canonical
fingerprints, advances the content revision, refreshes the lock, and vendors
the exact bytes. The Cloud and Foundry structural tests assert the same value.
The feasibility harness checks each session's own canary against both foreign
canaries, and pre-registers deterministic network, volume, and container names
so cleanup runs after timeout-after-side-effect outcomes; explicit Docker
resource-specific absence responses count as verified cleanup, while unrelated
"not found" errors remain cleanup failures.
The probe-timeout regression preserves `setup=passed` and `readiness=passed`,
leaves the undifferentiated model stage `pending`, and emits
`status=SETUP_BLOCKED` with `reason=probe_timeout`.
Early `SETUP_BLOCKED`, `READINESS_FAILED`, and
`MODEL_PREFLIGHT_FAILED` statuses preserve the stage that actually failed;
incomplete or malformed early reports leave later stages `pending` rather
than inferring a model failure.
Profile-store failures and offline provider `ImportError`/`RuntimeError`
failures are converted into sanitized evidence reports. Probe-exec `OSError`
also preserves passed setup/readiness attribution, and contention timeouts mark
unexecuted fresh-session and second-profile recall checks `blocked` rather than
`fail`.
The launcher also budgets the outer Docker exec for four bounded stream stages
and twelve bounded request calls; the focused regression independently asserts
that aggregate formula.

## Verified tuple

- Cloud artifact head: `3af3da24e8f8e516861f34ddaa85442bbe25eaa1`
- Foundry artifact head: `2626076973cfa52eec00eed265ab045b8b7b9ac5`
- Foundry final evidence head: `cae833ddace34ba92bd2670de1e8bf8edebd76d3`
- Foundry PR/document head reviewed: `7a92656e0d272fa7648c68cadd0b05131454d75c`,
  a documentation-only successor to the evidence code head. This record's
  containing correction is also documentation-only; the PR description carries
  the resulting current head. No harness code changed after the evidence code
  head.
- Contract revision: `14`
- Contract SHA-256: `f05ab0a1baf63551f426c288f0144484c813b5cda535bf1cf5d614fb7a22ea84`
- Fixture SHA-256: `2660d30ee73e8f3cebf94340ea1169019e3c937fd01a30bff6d0e16ecd54ab35`
- Lock SHA-256: `9005d25a8186d325a2efdcc42ec9e6cfe4d2d6c445088c9ba7a6b4d87429cb04`
- Contract, fixture, and lock bytes are identical across Cloud and Foundry;
  UTF-8/no-BOM/LF/final-newline and strict duplicate-key checks pass.

## Tests and boundaries

- Cloud contract tests: `7 passed`.
- Foundry vendor contract tests: `5 passed`.
- Foundry focused feasibility tests: `51 passed` from a clean checkout of the
  final evidence head.
- Final-head evidence regressions cover exact readiness output, post-turn
  assertion validation, success-status recall gating, the complete six-direction
  history-canary matrix, and timeout-after-side-effect cleanup for network,
  volume, and container resources, including rejection of unrelated cleanup
  errors that merely contain "not found". They also cover probe-timeout and
  early-stage attribution, incomplete/malformed early reports, profile-store
  and provider exception sanitization, probe-exec OS-error attribution,
  contention-timeout blocked states for all unexecuted recalls, and the
  independently asserted aggregate probe-exec budget.
- Foundry harness syntax compilation and scoped checks passed.
- Class A remains `INCONCLUSIVE_REVIEW_REQUIRED`; Class B remains
  `SETUP_BLOCKED`.
- The bounded real-Hermes lifecycle/profile-volume correction is included in the
  final evidence head; it remains harness tooling and does not claim production
  capability.
- No production implementation, merge, deployment, or live capability claim
  is included.
