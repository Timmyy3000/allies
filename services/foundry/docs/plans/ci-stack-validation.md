# Restore CI and cover stacked pull requests

Fix two observability tests that inherit an exhausted process-wide logging
limiter. Give each test a fresh limiter through monkeypatch; retain production
rate limits and the existing flood tests. Reproduce with a pre-exhausted limiter,
then run the locked backend/runtime validation suites.

The merged secret-scan finding is ordinary test-plan prose. Ignore only its
verified historical commit/path/rule/line fingerprint and reword that paragraph
to avoid repeating the false positive in future squashes. Keep all scanner rules.

Remove the PR target-branch restriction from CI, secret scan and Enkii. Include
retargeting and ready-for-review events, preserving push/release restrictions,
permissions, secret handling and the existing pull_request event trust model.
Verify the resulting checks on this independent PR into dev and on a temporary
feature-base probe before closing it. Do not merge the probe.

Validation: pre-exhausted limiter reproduction, affected pytest tests,
`DJANGO_DEBUG=true uv run --locked --project backend python scripts/validate.py`,
changed-file Ruff, Gitleaks on the original failing range and final diff,
and hosted CI/scan/review. Hosted repetition also exposed the profile preflight
read outside execution creation's bounded lock retry. Apply the existing helper
to that read and test a transient lock deterministically; persistence and tenant
validation stay unchanged. No database schema changes.
Rollback is a normal revert. Independent PRs into dev are the default; use
stacks only for necessary dependencies and document merge order explicitly.
