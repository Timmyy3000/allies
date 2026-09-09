# CLD-012 final Sol code review — revision 8 successor

Date: 2026-09-09
Reviewer: Sol review worker (agent 01a084fa-106d-7702-9fe3-f8dc5a1c52f0)
Cloud HEAD: `1897ce64d431eddf84086190cab59e653ea35704`
Foundry HEAD: `ee0846164b7f4a0a3c03ef783eca6da24f0285ab`

## Verdict

Accept revision-8 successor. No P0, P1, or P2 findings remain.

## Reviewed scope

- Cloud and Foundry `docs/contracts/routines-v1.md`
- Cloud and Foundry `docs/contracts/fixtures/routines-v1.json`
- Cloud and Foundry `docs/contracts/routines-v1.lock.json`
- Cloud `backend/allies/tests/test_routines_contract.py`
- Foundry `backend/runtime/tests/test_routines_contract.py`
- Cloud `docs/plans/cld-012-routines-contract.md`

The review verified both clean worktrees match their published remote heads,
exact byte parity across the three normative artifacts, and the narrow revision-
8 correction. `routine.result.title_snapshot` is required and copied exactly
from the accepted `routine.dispatch` title snapshot; `routine_revision` also
matches. The canonical result fingerprint and lock hashes are coherent. No
receipt, approval, dispatch-receipt, or production-runtime fields changed from
revision 7. Revision 7 remains the preserved accepted predecessor and was not
rewritten.

## Exact revision-8 hashes

- Contract: `9e355d7b8ead4d675cd79fef766faa634069117acb0e9927ad02efd8fe202cdc`
- Fixture: `70028e3e1935fc79b4d6bd4127facb4501c0a97492a808345921f423ec55cec8`
- Lock: `488bad850829212951991f78e34cfd00b3f575969385a35af36761a87c7278e8`

## Checks

- Cloud focused contract tests: **7 passed**.
- Foundry focused contract tests: **5 passed**.
- Cloud and correctly scoped Foundry Ruff checks: **passed**.
- Exact Cloud/Foundry artifact parity, lock-to-file SHA-256, canonical
  fingerprint, JSON, encoding/newline, and `git diff --check` validations:
  **passed**.
- Hosted Cloud PR checks: **4 passed, 0 failed, 1 skipped**.
- Hosted Foundry PR checks: **6 passed, 0 failed, 3 skipped**.

Class A remains `INCONCLUSIVE_REVIEW_REQUIRED`; Class B remains
`SETUP_BLOCKED`. No merge, deployment, or live capability claim is made.
