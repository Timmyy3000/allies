# Alpha PWA and onboarding handoff

## Identity
- Episode ID: alpha-pwa-onboarding-handoff
- Objective: Deliver AT-032, AT-033, and AT-039 in a focused web PR.
- Work type: implementation
- Route: fast
- Route reason: bounded web scope with cross-state onboarding queue and identity risk.
- Repositories: allies-interface
- Worktree/branch: `.forest/worktrees/at-032-033-039` / `web/fix/pwa-onboarding-handoff`
- Intended base branch: `origin/dev`
- Delivery path: pull request to `dev`; do not merge
- Brief: `docs/plans/alpha-pwa-onboarding-handoff-brief.md`
- Plan: `docs/plans/alpha-pwa-onboarding-handoff.md`
- HTML required and reason: no; concise Markdown is proportionate and no visual review artifact was requested.
- Command path/version provenance (closure commands): Forest v0.8.1; executable resolution pending closeout.

## Current State
- Phase: monitoring
- Status: active
- Last transition at: 2026-09-08
- Next action: dedicated Luna monitor follows current-head checks, Enkii, comments, and mergeability to the specified terminal condition.
- Blocking condition: none

## Decisions
| ID | Decision | Source | Affected phases |
| --- | --- | --- | --- |
| DEC-001 | Use the existing saved kickoff worker selectors unchanged. | `.agent/kickoff.yaml` | planning, review, implementation |
| DEC-002 | Nabu remains read-only unless accepted architecture must be reconciled. | user instruction | all |
| DEC-003 | Preserve the Forest worktree while the unmerged PR is monitored. | kickoff closeout contract | monitoring, closeout |
| DEC-004 | Enforce Ponytail full mode through implementation and the pre-PR over-engineering pass. | owner correction | planning, implementation, code-review |
| DEC-005 | Treat the checked-in `/app` route, manifest, Next config, and production build/smoke output as the implementation contract; `https://yourallies.io/app` and `/manifest.webmanifest` both returned 404 on 2026-09-08, so live deployment verification remains an explicit delivery caveat rather than prompting route invention. | repository evidence plus read-only live probe | planning, implementation, delivery |

## User Corrections
| At | Category | Correction | Artifacts updated |
| --- | --- | --- | --- |
| 2026-09-08 | implementation method | Activate Ponytail full; keep the shortest root-cause diff and smallest meaningful checks without weakening safeguards. | brief, episode state, plan worker handoff |
| 2026-09-08 | delivery path | Do not manufacture a diff or open an empty PR; prove existing behavior and close no-op if all criteria already hold, otherwise make the smallest root-cause change with one focused regression. | brief, episode state, worker handoff |

## Evidence Index
| Evidence | Path or URL | Why it matters |
| --- | --- | --- |
| Repository policy | `AGENTS.md`, `apps/web/AGENTS.md`, `ENGINEERING_STYLE.md` | Required workflow, Next.js preflight, validation, branch naming |
| Runtime/test configuration | `README.md`, `package.json`, `.github/workflows/ci.yml`, `vitest.config.ts` | Exact local and CI checks |
| Product tracker | Nabu `projects/allies/delivery/alpha-test-tracker.md` | Canonical AT-032/033 reports and scope |
| Product requirements | Nabu `projects/allies/product/allies-first-product-requirements.md` | Seamless owned-Ally creation and conversation intent |
| Conversation contract | Nabu `projects/allies/engineering/specs/conversation-and-streaming.md` | Queue, idempotency, identity, and first-content constraints |
| Decision log | Nabu `projects/allies/engineering/decisions/decision-log.md` | Interface/Cloud ownership and one-conversation boundary |
| Planner source inspection | `apps/web/app/app`, `app/manifest.ts`, `app/globals.css`, `next.config.ts`, `lib/pwa/pwa-install.tsx` | Existing `/app`, standalone detection, system-driven theme tokens; deployed origin/SHA not verified |
| Planner handoff inspection | `apps/web/app/home/home-workspace.tsx`, `app/account/account-client.tsx`, `lib/allies/authenticated-onboarding-flow.tsx`, `lib/allies/onboarding-handoff-screen.tsx` and existing tests | Immediate drawer dismissal races route/conversation readiness; preserve stable creation keys and queued-send ownership |
| Planner smoke configuration | `apps/web/package.json`, `apps/web/playwright.home-smoke.config.ts`, `apps/web/tests/home-smoke` | Production build, desktop/mobile Chromium, PWA WebKit checks |
| Saved worker selector | Main checkout `.agent/kickoff.yaml` (read-only; absent in isolated checkout) | Confirmed `astra_planning_worker`; configuration preserved |

## Planning Result
- Plan created: `docs/plans/alpha-pwa-onboarding-handoff.md`; revision 1.
- Started/completed: 2026-09-08 (initial run and focused revision).
- Decisions: reuse standalone detection and global theme tokens; coordinate created-Ally presentation with destination readiness; no new dependency/storage/backend contract.
- Assumptions: selected theme refers to existing `prefers-color-scheme` token contract; AT-039 authority is the user brief (not present in inspected tracker).
- Remaining evidence: installed Next routing guide preflight before code edits; production build/smoke gate. Live route 404s and unknown deployed SHA are delivery caveats under DEC-005.
- Revision 1: Home owns accepted identity/exchange; ConversationPane owns exact exchange readiness; incomplete snapshots have bounded reads/manual retry; accepted creation cannot dismiss or replay through stale routing/roster refresh.
- Nabu: read-only MCP inspection completed; installed/canonical skill version both 0.2.0.
- Validation basis: commands and acceptance matrix in plan; no implementation checks run by planner.

## Review Mode
- Combined or separate: separate
- Risk and policy basis: fast route and stateful queue/identity transition require dedicated simplicity and correctness reviews.

## Review Findings
| ID | Review | Severity | Disposition | Plan revision |
| --- | --- | --- | --- | --- |
| ADV-001 | adversarial | Major | resolved in independent re-review | revision 1 |
| ADV-002 | adversarial | Major | resolved in independent re-review | revision 1 |
| ADV-003 | adversarial | Question | resolved in independent re-review via DEC-005 | revision 1 |
| CR-001 | code review | P1 | fixed: release now requires selected-route correlation; focused delayed-route regression added | implementation |
| CR-002 | code review | P1 | fixed: account/workspace mismatch clears accepted handoff and retry state | implementation |
| CR-003 | code review | P2 | fixed: rendered pending-handoff test asserts overlay and roster suppression | implementation |
| CR-004 | code review | P2 | fixed: dark-scheme error color uses established readable error color | implementation |

## Validation
| Command/check | Head SHA | Result | At |
| --- | --- | --- | --- |
| `bun run typecheck` | final working diff | passed | 2026-09-08 |
| focused web Vitest suites (123 tests; final Home rerun 79 tests) | final working diff | passed | 2026-09-08 |
| `bun run lint:web` | final working diff | passed with 36 pre-existing warnings, 0 errors | 2026-09-08 |
| `bun run build:web` | final working diff | passed; `/app` and `/manifest.webmanifest` emitted | 2026-09-08 |
| `bun run --cwd apps/web test:home-smoke` | final working diff | 33 passed across desktop, mobile, PWA WebKit | 2026-09-08 |

## Delivery And Monitor
- Delivery mode: pull-request
- PR URL: https://github.com/alliesai/allies-interface/pull/41
- Head/base: web/fix/pwa-onboarding-handoff / dev
- Head SHA: 5660d0dfc4a2156727a61ba807b57a0f3b996f0f at monitor creation; delivery-record update commit follows
- Remote target SHA: 5660d0dfc4a2156727a61ba807b57a0f3b996f0f verified before delivery-record update
- Monitor status: active
- Monitor ID: 01a08158-a05b-7331-8103-7572aff24086
- Monitor terminal condition: complete Enkii mergeability score across code/security/policy plus all CU/tests passing, or concrete user-action blocker; never merge.
- Last verified checks/reviews: local validation green; Ponytail `Lean already. Ship.`; independent code review has no remaining P0-P2 findings. Initial GitHub state: Gitleaks passed; Interface CI and Enkii pending; preview deployment reported one failure and one pending run.

## Closeout
- Deployment/promotion: not in scope
- Forest worktree: present
- Cleanup authorization source: retain while PR is unmerged under kickoff contract
- Exact worktree owner at closeout:
- Live-use check/result (owner task and associated terminals/processes):
- Temporary retention owner: Codex monitor task `01a08158-a05b-7331-8103-7572aff24086`
- Retention revisit trigger: merge
- Retention revisit handoff: dedicated Luna/max monitor task `01a08158-a05b-7331-8103-7572aff24086`
- Post-merge worktree choice: pending
- Forest closure evidence (Forest state, Git registration, exact disk path):
- Ignored evidence/config retained (authorized location, names, and verification hashes only):
- Worktree disposition: retained for PR monitoring
- Temporary artifacts:
- Durable records reconciled: Nabu read-only; no product-direction change anticipated
- Terminal evidence: open PR #41, correct base/head branch, active monitor; final ready state pending external checks/reviews.

## Metrics
- Phase timestamps: intake/planning 2026-09-08
- Planning worker runs: 2
- Plan revisions: 1
- Adversarial review runs: 1
- Simplicity review runs: 0
- Implementation worker runs: 2
- Ponytail code-review runs: 2
- Correctness code-review runs: 2
- Context compactions observed: 0
- User correction count: 2
