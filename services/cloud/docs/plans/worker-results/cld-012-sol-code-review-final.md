# Code Review

- Head/base/SHA: Cloud `41f06a2c25093015af4190a178c849114c4fb28a` / `origin/dev` at the same SHA; Foundry `1d03ea557be757f4eca4c6b6478d542291169b14` / `origin/dev` at the same SHA. Review includes only the untracked CLD-012 delivery artifacts.
- Files reviewed: Cloud and Foundry revision-3 contract, fixture, lock, tests, Foundry feasibility harness and launcher, operations evidence, accepted plan, revision trail, and prior correctness reviews.
- Independent reviewer: yes
- Review mode and reason: separate final correctness/security/reliability review after CR-007 and CR-008 fixes; no simplicity or P3 findings.
- Started/completed at: 2026-09-09 (Europe/Berlin)

## Findings

| ID | Priority | Confidence | File:line | Evidence and impact | Suggested fix |
| --- | --- | --- | --- | --- | --- |
| CR-009 | P1 | 98/100 | `runtime/hermes-image/smoke_routine_sessions.py:892-935` | Class B records each interval immediately before awaiting `client.stream_profile()` and after the request returns, then treats overlap between those client-call intervals as proof that main and routine workers overlapped. Three concurrently submitted requests can have overlapping wait intervals even if Hermes queues and executes them strictly one at a time; the main call can also finish while a queued routine call remains outstanding. The prompts contain no barrier or other server-observable worker interval, and no test exercises this oracle. Consequently the harness can report `CAPABILITY_PASSED` while the profile-wide serialization that CLD-012 must disprove is still present. | Add a deterministic, server-observable barrier/tool step reached by all three live sessions and record start/end evidence from emitted worker/tool events. Require both routine sessions to reach the barrier before releasing main, then prove main completes while at least one routine has begun server-side and remains active. Fail closed when those events are absent or ambiguously ordered, and add a fake serialized-client test that must not pass the Class-B concurrency checks. |

## Coverage Checked

- Contract revision 3 and Cloud/Foundry byte parity: content `ba05f7ee14a958524462cc31e83a05fd9f16b242efc6fea180a12ae40015547d`, fixture `bc2fa9979a89f71ec57544bc07aa326e1bdc7b084f9c0ab1cee4c934a67d4a0a`, lock `ba9c2f5b3caf20ebbeae8e26c99740eb74402d84253341a137e5761e447d67cc`.
- Complete directional envelopes, canonical fingerprints, identity/correlation fields, lock metadata, and hash/encoding invariants.
- Recurring-only pause/resume chain and coherent post-delete get/list discovery timeline, including the revision-3 structural assertions.
- Current Foundry one-binding, unresolved-profile-lease, and occupied-claim safeguards; no production routine behavior is introduced.
- Launcher digest/source pinning, outbound-only bridge networking, credential-reference allowlisting and response bounds, redaction, authenticated readiness gating, setup/capability classification, and owned-resource cleanup.
- Class A overall deadline wrappers, simultaneous write barrier, persisted-marker recall, isolation checks, timeout handling, cleanup, and truthful `INCONCLUSIVE_REVIEW_REQUIRED` evidence.
- Class B `SETUP_BLOCKED` evidence and capability gating; the finding above prevents freeze because the successful concurrency oracle is not yet sound.
- Focused validation: Cloud contract tests passed (5); Foundry harness/launcher tests passed (12). Foundry backend contract/constraint tests could not collect because Django is unavailable in the invoked environment. Foundry Ruff found one import-order error in the untracked harness test; omitted as below P2. `git diff --check` found no tracked-diff whitespace errors (delivery files remain untracked).
