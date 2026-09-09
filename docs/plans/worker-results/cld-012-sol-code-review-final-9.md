# CLD-012 final Sol code review — revision 9 successor

Date: 2026-09-09
Reviewer: Sol review worker (agent 01a08521-9277-7030-bfd7-cc0cdcf10ef4)
Cloud normative HEAD: `e303c14ced1d3028ebb556a0664057737aa82f23`
Foundry vendor HEAD: `cffa731573ee9c6ae25b8cfca496dca28a74b512`

## Verdict

Accept revision 9. No actionable P0, P1, or P2 findings remain.

## Reviewed scope

- Cloud and Foundry `docs/contracts/routines-v1.md`
- Cloud and Foundry `docs/contracts/fixtures/routines-v1.json`
- Cloud and Foundry `docs/contracts/routines-v1.lock.json`
- Cloud `backend/allies/tests/test_routines_contract.py`
- Foundry `backend/runtime/tests/test_routines_contract.py`
- Cloud `docs/plans/cld-012-routines-contract.md`

The review verified exact Cloud/Foundry artifact parity and the bounded
revision-9 successor. Schedule generation starts at 1 and advances exactly
once through schedule update, pause, and resume, with all fixture metadata and
dispatch aligned at 1/2/3/4. Foundry-owned constraint evidence uses
`expected_constraint_outcome` rather than expanding the public result-code
vocabulary. Cloud dispatch correlation is separated from Foundry-assigned
execution, attempt, and generation identities. Revision-8 title-snapshot
behavior and both predecessor tuples remain preserved; no receipt, approval,
production-runtime, migration, deployment, or feature scope drift was found.

## Exact revision-9 hashes

- Contract: `891a9eb9932be9e7826baaf313ded7c6fd4f8526a661e0be5a83b6118fee76de`
- Fixture: `259577de2ea7e8343b266995767496d359aef196f1a19d6841e67ef133fb3343`
- Lock: `a9dbd56d70bc8e63c74988a85e2121527ab54d398d04c086538fc2f3e4f107de`

## Checks

- Cloud focused contract tests: **7 passed**.
- Foundry contract plus constraint tests: **8 passed**.
- Cloud Ruff check and format check: **passed**.
- Correctly scoped Foundry Ruff check: **passed**.
- Exact artifact parity, lock-to-file SHA-256, canonical fingerprints,
  duplicate-key JSON, encoding/newline, and `git diff --check`: **passed**.

Revision 8 remains preserved as the accepted title-snapshot intermediate;
revision 7 remains the historical published predecessor. Class A remains
`INCONCLUSIVE_REVIEW_REQUIRED`; Class B remains `SETUP_BLOCKED`. No merge,
deployment, or live capability claim is made.
