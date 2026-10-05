# Machine start retry backoff

Fast route; no visual artifact needed. Authorized for direct delivery to dev.

Scope: prevent provisioning and replacement start retries from overwhelming the
provider. Keep provider adapters, image publishing, and readiness contracts unchanged.

Approach: use capped exponential backoff (1/2/4/8 seconds) with jitter, respect
numeric and HTTP-date Retry-After values, and inspect machine state before retrying.
Wait for transitional machines using the existing bounded wait. Never issue another
start after the current phase deadline. Terminal and missing-machine errors propagate.

Acceptance: transient failures recover; repeated rate limits back off; starts that
completed despite an error are not repeated; Retry-After does not trigger an early
retry when it exceeds the deadline. Tests use simulated time.

Validation: locked uv pytest for machine-start backoff and workspace lifecycle;
locked uv ruff check/format check for changed Python; repository scripts/validate.py
for lockfiles, Django checks, migrations, backend and runtime tests.

Risk: a provider that remains unavailable still exhausts the existing deadline.
This addresses retry amplification, not every possible readiness failure. Rollback:
revert the focused commit. No migrations or image rebuilds. No unresolved decisions.

Completed validation: repository validation passed (467 backend tests, 2 skipped;
358 runtime tests, 5 skipped; lockfiles, Django, and migration checks passed).
After the final wait-state adjustment, 35 focused tests and all 17 runtime-release
tests passed. Backend Ruff, changed-file formatting, and diff whitespace checks passed.
Separate correctness and simplicity passes found no remaining actionable findings.
