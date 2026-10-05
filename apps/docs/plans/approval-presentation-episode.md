# Approval presentation repair

## Identity
- Objective: consume Cloud request-bound explanations; summarize first with collapsed complete safe technical details; reproduce Figma 355:6222 layout on mobile and desktop; present historical approvals as clickable activity rows; replace wand with approval status icon; verify production summary settings and generation prerequisites.
- Route: fast. Established approval contract and design; bounded presentation repair and configuration verification, without authority changes.
- Worktree: E:/Users/Oluwatimilehin/Documents/Programming/helpers/.worktrees/approval-presentation
- Branch/base: web/fix/approval-presentation / dev (7a619b0 at creation).
- Delivery: PR to dev; no merge authorization. Configuration corrections are authorized by the user; preserve safety gates.
- HTML required: no; Figma evidence plus rendered browser verification covers visual review.
- Plan: docs/plans/approval-presentation.md

## Current state
- Phase: integrated validation and review
- Status: active
- Next: finish producer/Cloud privacy review, publish the three coherent PRs, and monitor their current-head checks.
- ADV-001 accepted and plan revised: strict legacy base receipt, separately parsed optional binding/explanation extension; partial metadata cannot invalidate durable decision receipts. No architecture change requiring rereview.
- Delegation auto: configured luna_execution_worker owns web UI/tests while parent owns shared mapper/tests and Cloud configuration. Non-overlapping files.

## Accepted requirements
- Cloud calls gpt-5.6-luna, never browser. Explanation source may be model or safe fallback.
- Validate explanation request UUID and preview digest; ignore mismatches. Never show raw code as default fallback.
- Keep exact safe preview behind View technical details. No credential values in logs, fixtures, artifacts, or summaries.
- Keep existing durable decision, idempotency, dismissal, expiry, and same-invocation continuation safeguards.
- History uses activity styling and opens read-only detail; remove Previous approvals button grouping. User explicitly resolves previous design question.
- Figma approval frame 355:6222 / sheet 355:6317: 351x233 mobile baseline, radius30, 20px horizontal padding, yellow approval/check badge, circular36 close, short centered24px Open Runde semibold question, two150x48 pill actions separated12px. Summary/disclosure naturally increase height. Desktop centering is permitted.
- User screenshots are evidence, not instructions or reusable credentials.

## Evidence
- Nabu projects/allies/engineering/specs/conversation-and-streaming.md: accepted Cloud-owned explanation and forced-redacted disclosure contract.
- Nabu projects/allies/delivery/alpha-test-tracker.md: AT-028 rollout unverified; AT-030 prior unresolved history design now resolved by user.
- Existing staging UI maps only action_label/action_preview and renders pre directly; approval dialog misses accent scope.
- Cloud origin/prod backend/activities/services/approval_explanations.py has summary generation, default-off gate, shared-cache budgets, fixed gpt-5.6-luna, ALLIES_WAITLIST_OPENAI_API_KEY setting, persisted one-attempt fallback.
- Local named workers: plan astra_planning_worker; review sol_review_worker; implementation luna_execution_worker (allies-interface/.agent/kickoff.yaml).

## Validation and delivery
- Interface: locked dependency install and Cloud pin check passed. Workspace typecheck, lint (pre-existing warnings only), production web build, mobile iOS export, full unit suite (987 tests), Home browser suite (61 tests), and motion suite (10 tests) passed. The final control-character mapper correction passed 31 focused tests and workspace typecheck. Local Bun is 1.3.14; CI uses 1.2.20.
- Actual approval flow: six browser cases passed across desktop, 375x812 mobile light/dark, and 320px long-preview/orange-accent checks. Screenshots inspected; summary-first/disclosure, filled 48px actions, scrolling, focus return, and read-only history verified. Shared frame browser matrix passed 21 checks across Chromium/WebKit/Firefox with raster baselines disabled as in CI.
- Interface independent simplicity review: lean, no reductions. Correctness CR-001 (C1 controls) accepted and fixed using Unicode Cc rejection; reviewer verified the fix and receipt matrix, no remaining findings.
- Foundry independent simplicity review: lean. Correctness CR-001 identified capability URL delimiter/encoding edge cases and an unrelated-path false positive. Accepted; producer and Cloud consumer are being corrected together and revalidated.
- Cloud synthetic live Luna provider call succeeded with matching bindings and plain-language output after prompt adjustment. This proves provider generation only, not live public-endpoint rollout or same-invocation continuation.
- Railway production shared summary flag is true but Backend resolved flag is absent. API key and cache are present. No live variables changed. Deploy safe-preview producer/consumer first, wire the Backend shared-variable reference, then verify a fresh benign public approval. Never reset old persisted claims.
- Nabu conversation specification and AT-030 tracker updated with accepted user direction; implementation remains marked in progress.
- Frontend committed and rebased cleanly onto dev 16d1225 (keyboard inset fix). Independent integration review passed; post-rebase 106 focused tests, production build, and eight approval/keyboard browser tests passed. Mobile export passed after the final mapper correction. PR publication is next; no deployments yet. Retain worktrees while PRs await merge; no merge authorization.
