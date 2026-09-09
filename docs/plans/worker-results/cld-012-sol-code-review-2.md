# Code Review

- Head/base/SHA: Cloud `41f06a2c25093015af4190a178c849114c4fb28a` / `origin/dev` at the same SHA; Foundry `1d03ea557be757f4eca4c6b6478d542291169b14` / `origin/dev` at the same SHA. Review includes only the untracked CLD-012 delivery files.
- Files reviewed: untracked CLD-012 contract, fixtures, lock, tests, feasibility harness, operations note, accepted plan, and prior review in the two requested repositories.
- Independent reviewer: yes
- Review mode and reason: separate correctness/security/reliability post-fix review; no style or simplicity findings.
- Started/completed at: 2026-09-09 (Europe/Berlin)

## Findings

| ID | Priority | Confidence | File:line | Evidence and impact | Suggested fix |
| --- | --- | --- | --- | --- | --- |
| CR-007 | P1 | 99/100 | `docs/contracts/fixtures/routines-v1.json:164` | The fixture's single revision chain creates and updates a one-time schedule, then successfully pauses that same `routine_id` at revision 2 and resumes it at revision 3. This contradicts the accepted and normative rule that one-time routines cannot be paused, even though the linked `management-pause` case claims a recurring-schedule precondition at `:791`. The later delete at revision 4 is also followed by active get/list examples at later timestamps. Because the new consistency test checks receipt codes/states but never reconciles the referenced schedule or lifecycle, CLD-013 could adopt an invalid one-time pause transition or inconsistent post-delete behavior from the normative fixture. | Make the successful pause/resume vectors use a distinct recurring routine (or change the preceding saved schedule to recurring) and keep get/list on a coherent pre-delete timeline or distinct routine identity. Add assertions that each case's preconditions match the referenced request/current fixture state, including recurring-only pause and no active discovery after deletion. Increment `content_revision`, refresh all hashes, and vendor byte-identical artifacts to Foundry. |
| CR-008 | P2 | 95/100 | `runtime/hermes-image/smoke_routine_sessions.py:309` | `--timeout-seconds` still does not bound the full Class A probe. Provider initialization/status, the two initial `mnemosyne_remember` calls at `:309-318`, recall calls at `:355-357` and `:390-392`, and SQLite access execute synchronously on the main thread; any blocked provider call prevents the elapsed-time check at `:489` and cleanup from running. The new timeout test at `runtime/tests/test_routine_session_feasibility.py:387` covers only `_run_concurrent_writes`, so a hung initial write or recall can leave the documented bounded diagnostic running indefinitely. | Enforce one overall deadline around every provider/storage operation, preferably by running Class A in a terminable subprocess with an outer timeout; otherwise add deadline-aware wrappers for initialization, status, writes, recalls, and database inspection and fail closed before cleanup. Add blocking-fake tests for an initial write and recall, asserting bounded return and truthful non-pass status. |

## Coverage Checked

- Verified Cloud/Foundry contract, fixture, and lock hashes: content `925913dd9f11a713546644a5f394735aff19cc931cd7447a8c5e65a92e743d43`, fixture `406b15e265bc2d46f9865e71c56251e66470d392cd33563fdc2315adcd1d2fbb`, lock `b813d3180aec086c8c833e24126608bf6933515b75cd05633d517699590aa3d5`; revision is 2.
- Checked complete directional envelopes and reproducible fingerprints across management, dispatch, result, and approval messages.
- Checked current one-binding, unresolved-profile-lease, and occupied-claim safeguards without treating them as proof of future concurrency support.
- Checked launcher outbound reachability without published ports, digest/source pinning, credential-reference allowlisting and response bounds, sanitized failure reporting, readiness gating, owned-resource cleanup, and Class B status truthfulness.
- Checked Class A simultaneous contention, marker persistence/isolation, cleanup, timeout behavior, and evidence wording.
- Targeted validation: Cloud contract tests passed (5); Foundry harness/launcher tests passed (10). Foundry backend contract/constraint tests could not collect in the invoked environment because Django is unavailable.
