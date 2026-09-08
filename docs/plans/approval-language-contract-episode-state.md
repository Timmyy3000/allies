# Approval language and response contract

## Identity
- Episode ID: approval-language-contract-2026-09-08
- Objective: Deliver AT-025, AT-028, and the Cloud-owned durable approval response/state contract.
- Work type: implementation and pull request
- Route: full
- Route reason: user-facing authority presentation, provider I/O, tenant isolation, durable state, and a versioned cross-repository contract create high correctness and security consequences.
- Repositories: allies-cloud only
- Worktree/branch: `E:\Users\Oluwatimilehin\Documents\Programming\helpers\allies-cloud\.forest\worktrees\ft\approval-language-contract` / `ft/approval-language-contract`
- Intended base branch: `origin/dev`
- Delivery path: pull request into `dev`; no merge
- Brief: `docs/plans/approval-language-contract-brief.md`
- Plan: `docs/plans/approval-language-contract.md` and `.html`
- HTML required and reason: yes; explicit planning handoff and visual review of saved versus confirmed approval state. Repository policy makes HTML conditional and requires parity when produced.
- Command path/version provenance (closure commands): Forest CLI embedded agent contract read 2026-09-08; worktree retained while PR is open.

## Current State
- Phase: monitoring
- Status: active
- Last transition at: 2026-09-08
- Next action: monitor PR #35 current-head CI, CU/tests, Enkii reviews, comments, head changes, and mergeability; never merge.
- Blocking condition: none

## Decisions
| ID | Decision | Source | Affected phases |
| --- | --- | --- | --- |
| DEC-001 | Cloud owns product-facing summary and durable approval state; Luna is explanatory only. | Accepted Nabu decision, 2026-09-08 | planning, implementation, review |
| DEC-002 | Scope is Cloud-only unless an ownership/compatibility gap proves a concrete Foundry dependency. | User authorization | all |
| DEC-003 | Use existing kickoff worker selectors unchanged. | `.agent/kickoff.yaml` | planning, review, implementation |
| DEC-004 | Apply Ponytail full throughout and run a dedicated over-engineering pass before PR delivery; simplicity cannot remove required safeguards. | Owner correction, 2026-09-08 | planning, implementation, review |

## User Corrections
| At | Category | Correction | Artifacts updated |
| --- | --- | --- | --- |
| 2026-09-08 | implementation discipline | Activate `/ponytail full` for the episode. | brief, episode state, planning handoff |

## Evidence Index
| Evidence | Path or URL | Why it matters |
| --- | --- | --- |
| Repository policy | `AGENTS.md`, `ENGINEERING_STYLE.md` | Required ownership, trust, planning, validation, and Git conventions |
| Product tracker | Nabu `projects/allies/delivery/alpha-test-tracker.md` | AT-025, AT-028, AT-029 context |
| Conversation contract | Nabu `projects/allies/engineering/specs/conversation-and-streaming.md` | Current approval and streaming boundaries |
| Architecture | Nabu `projects/allies/docs/05-technical-architecture.md` | Cloud/Foundry ownership |
| Decisions | Nabu `projects/allies/engineering/decisions/decision-log.md` | Accepted Luna approval-explanation direction |
| Validation config | `README.md`, `Makefile`, `backend/pyproject.toml`, `.github/workflows/` | Required local and hosted checks |

## Review Mode
- Combined or separate: separate
- Risk and policy basis: provider I/O, durable authorization-adjacent state, tenant isolation, and contract compatibility require dedicated simplicity and correctness/security review.

## Review Findings
| ID | Review | Severity | Disposition | Plan revision |
| --- | --- | --- | --- | --- |
| ADV-001 | adversarial | Major | accepted; addressed in plan | Revision 1: 6/60s tenant and 30/60s global TTL buckets; one/four shared slots; fail-closed and cross-process tests. |
| ADV-002 | adversarial | Major | accepted; addressed in plan | Revision 2: redirect-rejecting HTTPRedirectHandler and hard-coded endpoint with constant/zero-forwarding tests, simplified by SIM-001. |
| ADV-003 | adversarial | Major | accepted; addressed in plan | Revision 1: ALLIES_APPROVAL_SUMMARIES_ENABLED defaults false until named producer revisions/tests prove redaction. |
| ADV-004 | adversarial | Major | accepted; addressed in plan | Revision 1: canonical request/digest/action-kind/policy fingerprint persisted and required by CAS; stale/migration/concurrency tests. |
| SIM-001 | simplicity | Simplify | accepted; addressed in plan | Revision 2: hard-coded Responses endpoint; no URL configuration/override validators; redirect refusal and constant tests retained. |
| SIM-002 | simplicity | Simplify | accepted; addressed in plan | Revision 2: full binding metadata internal, narrow public explanation, action_kind in technical_details, no redundant DTO layers. |
| SIM-003 | simplicity | Simplify | accepted; addressed in plan | Revision 2: parameterized explanation/contract risks and named unchanged regression tests; query count only for new traversal. |
| SIM-004 | simplicity | Keep | accepted; preserved | Revision 2 retains one JSON field and durable fallback/CAS; no table, queue, worker, durable lease, or index. |
| SIM-005 | simplicity | Keep | accepted; preserved | Revision 2 reuses cache/rate-limit primitives with private constant-sized expiring slots; no framework. |
| PT-001 | ponytail | Simplify | resolved | Removed unreachable aggregate-length check. |
| PT-002 | ponytail | Simplify | resolved | Removed redundant JSON decode exception entries. |
| PT-003 | ponytail | Simplify | resolved | Narrowed provider-output validator to the real internal source type. |
| PT-004 | ponytail | Simplify | resolved | Collapsed duplicate fallback-save branches and removed the always-true claim flag. |
| CR-001 | code review | P1 | resolved | Cross-site/untrusted GET uses side-effect-free detail and cannot call the provider or persist explanation state. |
| CR-002 | code review | P2 | resolved | Every response read applies the remaining monotonic deadline to the socket. |
| ENKII-AL04 | policy review | P2 | resolved | Re-read and reconcile the scoped approval under lock after provider I/O; return the fresh row on both success and fallback paths, with a concurrent-decision regression test. |

## Validation
| Command/check | Head SHA | Result | At |
| --- | --- | --- | --- |
| `uv run python manage.py check` | working tree | passed | 2026-09-08 |
| `uv run python manage.py makemigrations --check --dry-run` | working tree | passed | 2026-09-08 |
| `uv run ruff check` (changed Cloud files) | working tree | passed | 2026-09-08 |
| `uv run pytest activities/tests/test_approval_explanations.py -q` | working tree | 13 passed | 2026-09-08 |
| `uv run pytest activities/tests/test_approval.py -q` | working tree | 29 passed, 2 skipped | 2026-09-08 |
| `make check` | working tree | passed | 2026-09-08 |
| `make lint` | working tree | passed | 2026-09-08 |
| `make test APP=activities/tests/test_approval_explanations.py` | working tree | 15 passed | 2026-09-08 |
| `make test APP=activities/tests/test_approval.py` | working tree | 30 passed, 2 skipped | 2026-09-08 |
| `make test APP=activities/tests` | working tree | 101 passed, 3 skipped | 2026-09-08 |
| `uv run pytest` | working tree | 621 passed, 23 skipped | 2026-09-08 |
| `uv run pytest config/tests/test_api_contract.py` | working tree | 8 passed | 2026-09-08 |
| `uv run ruff format --check .` | working tree | passed | 2026-09-08 |
| `make test APP=activities/tests/test_approval_explanations.py` | working tree after ENKII-AL04 fix | 17 passed | 2026-09-08 |
| `make test APP=activities/tests/test_approval.py` | working tree after ENKII-AL04 fix | 30 passed, 2 skipped | 2026-09-08 |
| `make check` | working tree after ENKII-AL04 fix | passed | 2026-09-08 |
| `make lint` | working tree after ENKII-AL04 fix | passed | 2026-09-08 |
| `make test APP=activities/tests` | working tree after ENKII-AL04 fix | 105 passed, 3 skipped | 2026-09-08 |
| `uv run ruff format --check .` | working tree after ENKII-AL04 fix | passed | 2026-09-08 |
| `uv run pytest` | working tree after ENKII-AL04 fix | 625 passed, 23 skipped | 2026-09-08 |

## Implementation checkpoint
- Changed only Cloud approval surfaces: `activities/models.py`, additive migration `0004_approval_explanation.py`, `activities/services/approval_explanations.py`, typed approval presentation/schemas/API, `activities/services/projection.py`, OpenAPI examples, settings, and focused tests.
- AT-025 boundary copy is `Waiting for your approval` for rich actionable approvals and `Needs your attention` for legacy attention-only events; existing technical action fields remain complete and redacted by the upstream contract.
- AT-028 uses a Cloud-only `gpt-5.6-luna` Responses projection with no tools or authority fields, strict request/digest/fingerprint binding, fixed endpoint with redirect rejection, bounded reads/tokens/deadline, fail-closed tenant/global budgets, durable fallback/CAS, and privacy-safe operation events. `ALLIES_APPROVAL_SUMMARIES_ENABLED` defaults to false; no provider transmission is enabled without named Foundry producer redaction evidence.
- The public `approval.v1` contract preserves `message_id` and `conversation_turn_ordinal`, adds `decision_recorded`, and keeps approval detail technical disclosure separate from the four-field explanation. Decision delivery/idempotency and Foundry contracts were not changed.
- Focused tests cover closed/malformed/unsafe output, fixed URL and redirect refusal, timeout/provider fallback, budget denial, stale binding CAS, foreign-user isolation, durable fallback, one-attempt model persistence, and no browser/provider decision coupling. Existing approval tests cover decision replay and delivery behavior.
- Post-Enkii AL-04 fix: the provider completion path re-reads and reconciles the scoped approval under a short lock before returning, so concurrent decisions or deadlines cannot produce stale response state; success and fallback paths are covered.

## Delivery And Monitor
- Delivery mode: pull-request
- PR URL: https://github.com/alliesai/allies-cloud/pull/35
- Head/base: `ft/approval-language-contract` / `dev`
- Head SHA: material-fix working tree pending commit/push (parent `a66a172c9e0ae1f9f683c2cbedb601a245694d08`)
- Remote target SHA: a66a172c9e0ae1f9f683c2cbedb601a245694d08 (last hosted head)
- Monitor status: active
- Monitor ID: 01a08166-fd9d-72c2-9243-e18c1213277c
- Monitor terminal condition: current-head CI/CU/tests pass and Enkii reports complete/full mergeability across code, security, and policy review; never merge.
- Last verified checks/reviews: local post-fix full suite and formatting passed; fresh Ponytail review found no cut; independent correctness/security review has no P0-P2; hosted a66a172 checks pass and Enkii code/security are 5/5, while policy AL-04 re-review awaits the pushed fix.

## Closeout
- Deployment/promotion: out of scope
- Forest worktree: present
- Cleanup authorization source: retain while PR is open per kickoff contract
- Exact worktree owner at closeout: codex
- Live-use check/result (owner task and associated terminals/processes): pending
- Temporary retention owner: Codex task 01a08166-fd9d-72c2-9243-e18c1213277c
- Retention revisit trigger: merge
- Retention revisit handoff: Codex task 01a08166-fd9d-72c2-9243-e18c1213277c
- Post-merge worktree choice: pending
- Forest closure evidence (Forest state, Git registration, exact disk path): pending
- Ignored evidence/config retained (authorized location, names, and verification hashes only): `.agent/kickoff.yaml`, unchanged selector configuration
- Worktree disposition: retain while PR is open
- Temporary artifacts: none
- Durable records reconciled: pending
- Terminal evidence: PR #35 open against dev; monitor task active; merge unauthorized.

## Metrics
- Phase timestamps: intake 2026-09-08; workspace 2026-09-08; planning started 2026-09-08
- Planning worker runs: 3
- Plan substantive revision count: 2
- Plan acceptance: revision 2, 2026-09-08, existing user authorization and accepted review dispositions
- Adversarial review runs: 1
- Simplicity review runs: 1
- Implementation worker runs: 1
- Ponytail code-review runs: 2 (initial plus post-ENKII-AL04 fix)
- Correctness code-review runs: 3 (initial, focused re-review, plus post-ENKII-AL04 fix)
- Context compactions observed: 0
- User correction count: 1
