# CLD-012 revision 3 disposition

Source: cld-012-sol-review-2.md (unchanged). Target: ../cld-012-routines-contract.md.
Status: addressed in plan; independent re-review pending.

| Finding | Explicit correction | Enforcement/evidence owner |
| --- | --- | --- |
| SOL2-001 | Resume/due lock-winner rows, candidate revision/generation fence, strictly future resume instant, result codes/outbox/snapshot assertions | CLD-013 PostgreSQL tests; CLD-012 metadata only |
| SOL2-002 | One durable action-attempt identity, monotonic dispatch states, bounded reconciliation, exact crash/receipt-loss outcomes, no non-idempotent or whole-prompt replay | FND-012 action dispatch/receipt enforcement |
| SOL2-003 | Existing provider integration/bootstrap hooks identified; absent complete local launcher explicitly SETUP_BLOCKED; one bounded launch_routine_probe.py planned with secret-safe lifecycle/readiness/probe/cleanup | CLD-012 future harness execution; offline/fake launch tests cannot establish capability |

Prior SOL-001..005 safeguards remain. Product scope and full template retained; HTML is not required. No production code, Nabu changes, live proof or reviewer acceptance claimed.
