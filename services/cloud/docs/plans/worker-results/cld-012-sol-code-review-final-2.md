# Code Review

- Head/base/SHA: Cloud `41f06a2c25093015af4190a178c849114c4fb28a`; Foundry `1d03ea557be757f4eca4c6b6478d542291169b14`. Scope was limited to untracked CLD-012 artifacts in the two requested worktrees.
- Independent reviewer: yes
- Review mode: separate final correctness, security, reliability, race/TOCTOU, contract-parity, bounded-timeout, and evidence-truthfulness review.
- Completed: 2026-09-09 (Europe/Berlin)

## Findings

| ID | Priority | Confidence | File:line | Evidence and impact | Suggested fix |
| --- | --- | --- | --- | --- | --- |
| CR-010 | P1 | 99/100 | `runtime/hermes-image/launch_routine_probe.py:38-40`, `runtime/hermes-image/launch_routine_probe.py:377-393`, `runtime/hermes-image/launch_routine_probe.py:594-608` | The outer Class B trust boundary accepts `CAPABILITY_PASSED` when the payload contains only passing readiness, model-preflight, and `real_session_turns` checks. It does not require `server_observable_barrier`, `main_and_routine_overlap`, or `main_completion_while_routine_active` to exist and pass. A focused invocation confirmed `_has_class_b_evidence()` returns `True` for a payload containing only those three checks. The current inner probe blocks honestly, and the serialized-client negative test passes, but a malformed, stale, or future probe payload can still be promoted to capability proof without deterministic server-observable evidence. This leaves CR-009 unresolved at the launcher acceptance boundary. | Add the three server-observable concurrency checks (and any required event-order/barrier evidence fields) to `CLASS_B_REQUIRED_CHECKS`; require each to equal `pass`, reject duplicate check names, and require the payload status to be consistent with all required checks. Add a launcher test proving a `CAPABILITY_PASSED` payload with only client-await overlap or missing barrier/event checks remains `SETUP_BLOCKED`/evidence-incomplete. |
| CR-011 | P2 | 97/100 | `runtime/hermes-image/launch_routine_probe.py:587-608`, `runtime/hermes-image/smoke_routine_sessions.py:1006` | The inner probe intentionally exits `1` for `CAPABILITY_FAILED`, but the launcher treats every nonzero probe exit as `SETUP_BLOCKED` before parsing an otherwise valid JSON report. Therefore a real, fully initialized Hermes capability failure can never be surfaced as `CAPABILITY_FAILED`; it is mislabeled as missing setup, weakening the feasibility artifact's diagnostic truthfulness and contradicting the documented stage separation. | Parse and validate the final JSON payload regardless of exit code. Accept exit `0` only with valid `CAPABILITY_PASSED`, exit `1` only with valid `CAPABILITY_FAILED`, and exit `2` only with valid `SETUP_BLOCKED`; treat missing, malformed, contradictory, or other exit/status combinations as incomplete evidence. Add a launcher test for a complete `CAPABILITY_FAILED` payload returned with exit code `1`. |

## Validation Performed

- Verified Cloud and Foundry shared artifacts are byte-identical and match the required revision-3 SHA256 values: contract `ba05f7ee14a958524462cc31e83a05fd9f16b242efc6fea180a12ae40015547d`, fixture `bc2fa9979a89f71ec57544bc07aa326e1bdc7b084f9c0ab1cee4c934a67d4a0a`, lock `ba9c2f5b3caf20ebbeae8e26c99740eb74402d84253341a137e5761e447d67cc`.
- Confirmed the pinned-image Class A evidence remains `INCONCLUSIVE_REVIEW_REQUIRED`: one `OFFLINE_DIAGNOSTICS_FAILED` run and two `CLASS_A_PASSED` runs. Confirmed Class B remains `SETUP_BLOCKED` with no capability claim.
- Confirmed `test_server_concurrency_oracle_rejects_serialized_client_overlap` exists and passes; the inner probe currently blocks all concurrency checks pending server-observable barrier evidence.
- Passed Cloud contract tests: 5 tests.
- Passed Foundry backend contract/constraint tests with `DJANGO_DEBUG=true`: 8 tests.
- Passed Foundry runtime feasibility/launcher tests: 13 tests.
- Reviewed only untracked CLD-012 files; no implementation files were edited and no commit or PR was created.
