# Web chat reliability polish

## Identity
- Episode ID: web-chat-reliability-polish
- Objective: Fix 13 reported web chat bugs (autoscroll, file previews, markdown preview, input padding, approvals polling, mascot overlap, routines manager, echo prompt, latency/failures, refresh scroll) in allies-interface web only
- Work type: bug-fix polish + minimal routines manager + 2 investigations (approvals polling, markdown preview)
- Route: full
- Route reason: 13 items cross-cutting chat critical journey, includes new UI surface (routines manager), ambiguous file-preview location (file-sharing branches vs dev), high user-visible consequence, needs coordinated scroll/polling/state fixes
- Repositories: allies-interface (apps/web only; packages/cloud-client read-only for contract mapping)
- Worktree/branch: C:\Users\ASUS\Desktop\projects\allies\allies-interface-web-chat-polish / web/chat-reliability-polish
- Intended base branch: dev
- Delivery path: pull-request (small coherent PRs per AGENTS.md, target 200-500 lines; split if >1000)
- Brief: this file + user bug list in chat 2026-09-17
- Plan: docs/plans/web-chat-reliability-polish.md (to be created by plan-it)
- HTML required and reason: no — Markdown sufficient unless planning worker finds visual review needed for file preview / routines manager variants

## Current State
- Phase: delivery
- Status: active
- Last transition at: 2026-09-18 - latest dev integrated and blank PDF preview fixed with normalized private PDF bytes plus an unsandboxed browser viewer
- Next action: record final PDF review, commit and force-with-lease push the rebased PR 69 branch, then monitor fresh hosted checks
- Blocking condition: none

## Decisions
| ID | Decision | Source | Affected phases |
| --- | --- | --- | --- |
| D1 | Scope = all 13 items together | user 2026-09-17 | planning, implementation |
| D2 | Surface = web only (mobile excluded, can't test) | user 2026-09-17 | planning, implementation, validation |
| D3 | Delivery = isolated worktree + PR to dev | user 2026-09-17 + AGENTS.md web/ naming | implementation, pr-creation, monitoring, closeout |
| D4 | Routines manager = minimal list + pause/resume/delete on existing Cloud contract | user 2026-09-17 | planning, implementation |
| D5 | File-preview fixes must locate code first: dev has no pdf/docx preview matches; file-sharing lives on ft/cld-010-file-sharing (cloud) / ft/fnd-011 (foundry). Plan must resolve base/merge strategy | evidence 2026-09-17 | planning |
| D6 | Approvals polling + markdown preview are investigate-then-fix within same episode | user bug list | planning, implementation |
| D7 | Preview modal extended in place (ImageLightbox + skeleton + multi-type, no new dep) per explicit user correction overriding SIM-003 full-render cut | user 2026-09-17 | implementation |
| D8 | Close episode at PR-open-conflicting; do NOT blind-rebase over teammates' file work (#64-#68) without owner authorization | orchestrator 2026-09-17 | closeout |
| D9 | Rebase onto origin/dev 486ae6c via reset + re-apply (not blind merge): approvals fix integrated with #59 error classification; sizes fixed in attachments UI where the bug actually shows; ImageLightbox extension re-applied | owner instruction 2026-09-17 ("review dev, resolve conflicts; close PR if dev resolves it") | implementation, closeout |
| D10 | Composer root cause proven by Playwright measurement (desktop media query centers collapsed text at 12px but flex-end sinks expanded single-line text to 18px); fix centers content div in expanded state, verified 12/12/12 across empty/typed/cleared | evidence 2026-09-17 | implementation |
| D11 | P9 echo: no client path copies user content into assistant text (mergeTurnModels audited); per ADV-003 no client mask — server-side triage follow-up recorded. Terminal states already satisfy one-copy-one-action; routines manager already wired on dev (#44/#47), no build needed | evidence 2026-09-17 | implementation |
| D12 | PDF previews use a private blob forced to application/pdf and an unsandboxed iframe so Chromium's isolated built-in PDF viewer can render it; no PDF renderer dependency | owner screenshot + headed Chromium evidence 2026-09-18 | implementation, validation |

## User Corrections
| At | Category | Correction | Artifacts updated |
| --- | --- | --- | --- |
| 2026-09-18 | Delivery | Make existing Interface PR 69 merge-ready by resolving current-head CI and review blockers. | Polling, scroll compatibility, browser expectations, validation, and independent reviews completed |
| 2026-09-18 | Scope | Fix the blank PDF preview in PR 69 if it is reasonably contained. | Root cause confirmed as iframe sandbox; contained frontend fix and regression coverage added |

## Evidence Index
| Evidence | Path or URL | Why it matters |
| --- | --- | --- |
| Approvals constant polling | apps/web/app/home/conversation-approvals.tsx:77,143 refetchInterval 3000 + 1s now-timer | root cause of constant approvals polling report |
| Chat scroll follow logic | apps/web/app/home/home-workspace.tsx:2049,2197 + conversation-frame.tsx:94,123 | autoscroll + refresh-scroll bugs |
| Composer + home styles | apps/web/app/home/home.module.css:1198-1355,1719-1748 + conversation-frame-primitives.tsx:454 | input padding bug |
| Markdown render | apps/web/app/home/conversation-frame.tsx:46,254 Streamdown static | echo/markdown preview baseline |
| Routine UI stubs only in dev | apps/web chat-frame fixtures + debug routine-card; real manager missing | routines manager is new UI |
| File preview absent in dev | grep pdf/docx/skeleton in apps/web = no chat preview matches | must check ft branches / staging for actual preview code |
| Cloud file branch | allies-cloud ft/cld-010-file-sharing | file backend contract source |
| Mobbin markdown patterns | 20 web screens: rendered doc modal + metadata sidebar most common (Fabric, Craft, Dropbox Dash); inline rendered md (Manus, Mistral, Basecamp) | informs markdown preview choice |
| Plan template | docs/templates/PLAN_TEMPLATE.md | full plan format |
| Repo policy | AGENTS.md, ENGINEERING_STYLE.md web/ naming, small PRs | delivery constraints |

## Review Mode
- Combined or separate: separate
- Risk and policy basis: full route with new UI + polling/state changes; keep correctness and simplicity passes distinct

## Review Findings
| ID | Review | Severity | Disposition | Plan revision |
| --- | --- | --- | --- | --- |
| ADV-001 | adversarial: routine+file contracts absent on dev | Blocker | accept: gate Phase 3 on Phase 1 contract artifact, no invented endpoints, no chat-fallback data | require exact paths + JSON before preview/manager PR |
| ADV-002 | adversarial: cross-repo base strategy missing | Blocker | accept: add sequencing, owner, rebase vs merge, OpenAPI pin, merge-block | add sequencing section |
| ADV-003 | adversarial: echo guard masks server truth | Blocker | accept: root-cause comparison first, narrow equality, no full-content logs | narrow guard + Cloud-escalation path |
| ADV-004 | adversarial: autoscroll root cause unverified | Major | accept: measure which signal stalls, reconcile follow flags, reduced-motion gate, jump-to-latest spec | Phase 2 measurement step |
| ADV-005 | adversarial: approvals polling underspecified + auto-open | Major | accept: interval table, background false, focus rules, gate auto-open | specify conditional polling |
| ADV-006 | adversarial: file trust/bounds | Major | accept: allowlist, MIME sniff, max bytes, sandbox, no-log | validation boundary per AL-02/AL-07 |
| ADV-007 | adversarial: refresh restore races pagination | Major | accept: settle signal, namespaced anchor+TTL, fallback, privacy | id-anchored restore spec |
| ADV-008 | adversarial: scope vs PR size, rollback | Major | accept: per-PR split table, merge order, per-PR rollback | add split table |
| ADV-009 | adversarial: tests harness mapping | Major | accept: map acceptance to Vitest vs Playwright, no ms thresholds | harness mapping + fixture policy |
| ADV-010 | adversarial: markdown threshold/metadata/dialog | Major | accept + SIM-001/002: single BottomSheet + Streamdown, no invented filename, define long threshold | lock single dialog pattern |
| ADV-011 | adversarial: a11y reduced-motion | Minor | accept: gate all animation, live-region + focus | per-surface checks |
| ADV-012 | adversarial: composer legacy CSS | Minor | accept + SIM-009: confirm which composer ships, delete or dated defer, no brittle metrics | confirmation artifact |
| ADV-013 | adversarial: reliability may be server-side | Question | accept: Phase 4 triage gate, preserve distinct retry paths | stop-and-file-Cloud criteria |
| SIM-001 | simplicity: single BottomSheet for markdown | Simplify | accept | reuse BottomSheet modal only |
| SIM-002 | simplicity: cut metadata sidebar | Simplify | accept: optional-only-if-model-has-it | title + body only |
| SIM-003 | simplicity: cut full pdf/docx render + new dep | Remove | accept per AL-11: native-only images + explicit unsupported card | no pdf.js/mammoth |
| SIM-004 | simplicity: keep size formatter | Keep | accept: single pure helper, stdlib only | 1024 + Intl.NumberFormat |
| SIM-005 | simplicity: skeleton as CSS state | Simplify | accept: no named component | fixed-height row + role=status |
| SIM-006 | simplicity: reuse queries.ts conditional pattern | Simplify | accept: no bespoke polling util | function refetchInterval + background false |
| SIM-007 | simplicity: conditional now-tick, no auto-open | Simplify | accept | tick only with deadline items, explicit open |
| SIM-008 | simplicity: extend existing follow path + minimal anchor | Simplify | accept: no parallel scroll system | rAF + reduced-motion + sessionStorage anchor |
| SIM-009 | simplicity: composer CSS-only + dead CSS delete/defer | Simplify | accept | stabilize shipped composer |
| SIM-010 | simplicity: defer routines CRUD before contract | Defer | accept: props-only extensions, gated mutations | no speculative client per AL-08 |
| SIM-011 | simplicity: cut latency fetch layer | Remove | accept: reuse SSE/visibility/Abort/idempotency/cursors | copy honesty only |
| SIM-012 | simplicity: narrow echo guard, no terminal machine | Simplify | accept | guard proven path only |
| SIM-013 | simplicity: reuse existing test files | Simplify | accept: no new harness | colocate tests |
| MERGE-PONY | ponytail review of the merge-readiness patch | Clean | accept | "Lean already. Ship." |
| MERGE-CR | correctness review of the merge-readiness patch | Clean | accept | no P0-P2 findings; independent focused suite 127/127 |
| CR-PDF-001 | initial PDF test used an invalid fixture and did not prove the browser viewer could load it | P2 | resolved | valid one-page PDF fixture with xref/page tree; blob MIME assertion; headed Chromium viewer contentType application/pdf passed |

## Validation
| Command/check | Head SHA | Result | At |
| --- | --- | --- | --- |
| git worktree list | f21e5ff | worktree created | 2026-09-17 |
| git diff --check | f21e5ff + uncommitted P4 | clean | 2026-09-17 |
| bun install --frozen-lockfile | 5045e55 | pass, 752 packages in 90s (retry with 600s timeout) | 2026-09-17 |
| bun --filter web lint (old base f21e5ff) | 5045e55 | 0 errors, 37 warnings | 2026-09-17 |
| bun run test:run (old base) | 5045e55 | 846 passed, 116 files | 2026-09-17 |
| bun run build:web (old base) | 5045e55 | pass | 2026-09-17 |
| verify:chat-frames (old base) | 5045e55 | pass (runtime + 25-frame manifest + bundle boundary) | 2026-09-17 |
| targeted tests (new base 486ae6c) | rebased, uncommitted | 25 passed: 15 approvals + 2 file-size + 6 file-preview + 2 attachment-picker | 2026-09-17 |
| bun --filter web lint (new base) | rebased, uncommitted | 0 errors, 48 warnings (all pre-existing) | 2026-09-17 |
| bun run test:run full (new base) | rebased, uncommitted | 1054 passed / 1 failed: routines rev-9 fixture SHA (pre-existing Cloud drift, proven on clean dev via stash); claim-invite file-level failure (pre-existing missing input-otp module, proven on clean dev) | 2026-09-17 |
| typecheck/build (new base) | rebased, uncommitted | fail only in claim-invite-client.tsx input-otp (pre-existing dev breakage, proven on clean dev via stash; untouched by this episode) | 2026-09-17 |
| verify:chat-frames (new base) | rebased, uncommitted | runtime + manifest pass; bundle boundary pass | 2026-09-17 |
| round-2 targeted (new base) | rebased, uncommitted | frame 58 + workspace incl. 3 new restore tests pass; composer fix verified by live Playwright geometry (12/12/12); markdown modal 2 new tests pass | 2026-09-17 |
| bun run test:run full round-2 (new base) | rebased, uncommitted | only pre-existing failures: claim-invite input-otp module + routines rev-9 fixture (both proven on clean dev) | 2026-09-17 |
| bun --filter web lint round-2 | rebased, uncommitted | 0 errors, 49 warnings (all pre-existing) | 2026-09-17 |
| focused approvals + workspace tests | f6c5897 + uncommitted merge fix | 127/127 passed; scroll restoration no longer emits jsdom errors | 2026-09-18 |
| web typecheck / lint / build | f6c5897 + uncommitted merge fix | pass / 0 errors (49 existing warnings) / pass | 2026-09-18 |
| previously failing browser cases | f6c5897 + uncommitted merge fix | 12/12 passed on desktop and mobile projects | 2026-09-18 |
| full web Home browser suite | f6c5897 + uncommitted merge fix | 65/65 passed across Chromium, mobile Chromium, and PWA WebKit | 2026-09-18 |
| bun run test:run full | f6c5897 + uncommitted merge fix | 1071 passed / 1 Windows-only raw fixture hash mismatch in packages/cloud-client routines revision 9; hosted Linux CI previously passed this fixture; zero unhandled scroll errors | 2026-09-18 |
| latest dev integration | rebased onto 2286afa | clean three-commit rebase over response presentation modes PR 70 | 2026-09-18 |
| focused approvals + workspace tests after rebase | c3f2c74 + PDF fix | 142/142 passed | 2026-09-18 |
| web typecheck / lint / build after rebase | c3f2c74 + PDF fix | pass / 0 errors (49 existing warnings) / pass | 2026-09-18 |
| full Home browser suite after rebase | c3f2c74 before PDF fix | 71/71 passed across Chromium, mobile Chromium, and PWA WebKit | 2026-09-18 |
| private file browser suite with PDF regression | c3f2c74 + PDF fix | 8/8 headless desktop/mobile; generated valid PDF blob is application/pdf and iframe is unsandboxed | 2026-09-18 |
| headed Chromium PDF viewer | c3f2c74 + PDF fix | pass; generated PDF loaded with document.contentType application/pdf in Chromium's built-in viewer | 2026-09-18 |

## Delivery And Monitor
- Delivery mode: pull-request
- PR URL: https://github.com/alliesai/allies-interface/pull/69
- Head/base: web/chat-reliability-polish / dev
- Head SHA: c3f2c74 before the PDF follow-up commit (rebased commit series; final remote SHA to be verified after push)
- Remote target SHA: 2286afa (latest origin/dev, including response presentation modes PR 70)
- Monitor status: not-applicable
- Monitor ID: none (no monitor automation in this harness; one-time gh check done at closeout)
- Monitor terminal condition: n/a
- Last verified checks/reviews: local validation and independent merge-readiness reviews complete; final hosted checks await the rebased PDF-fix push. PR remains unmerged.

## Closeout
- Deployment/promotion: none (unmerged)
- Forest worktree: not-applicable (plain git worktree used; no .forest in interface)
- Cleanup authorization source: none — worktree intentionally retained (unmerged PR branch + episode records)
- Post-merge worktree choice: pending (no merge yet)
- Forest closure evidence: n/a
- Worktree disposition: retained at C:\Users\ASUS\Desktop\projects\allies\allies-interface-web-chat-polish
- Temporary artifacts: none
- Durable records reconciled: plan + episode state on branch
- Terminal evidence: PR #69 updated on new base; dev-overlap review complete (approvals polling + sizes NOT resolved on dev; both fixes reintegrated + attachments sizes fixed); validation as above with only pre-existing dev failures remaining
- Dev-overlap verdicts 2026-09-17: (1) approvals unconditional 3s polling + auto-open STILL on dev (#59 changed presentation only) — our fix retained, integrated with error classification; (2) file sizes on dev use decimal (bytes/1e6).toFixed(1) MB — still the reported bug — fixed via formatFileSize in picker + files hook + modal; (3) no skeleton loader on dev attachments — skeleton added to shared preview modal; (4) ImageLightbox unchanged on dev — extension re-applied cleanly; (5) routines manager + remaining 11 bugs deferred; (6) routines rev-9 fixture + claim-invite input-otp failures are pre-existing dev breakage, proven via stash, untouched by this episode

## Metrics
- Phase timestamps: intake 2026-09-17, planning started 2026-09-17, plan v1 2026-09-17, reviews 2026-09-17, plan v2 2026-09-17, implementation P4 started 2026-09-17
- Planning worker runs: 2 (v1 + revision)
- Adversarial review runs: 1 (Needs revision, 3 Blocker / 7 Major / 2 Minor / 1 Question)
- Simplicity review runs: 1 (Simplification recommended, 11 Simplify/Remove + 1 Defer + 1 Keep)
- Implementation worker runs: 0 (orchestrator direct for P4)
- Ponytail code-review runs: 1 (clean: "Lean already. Ship.")
- Correctness code-review runs: 1 (clean: no P0-P2 findings)
- Context compactions observed: 0
- User correction count: 4 (1: extend existing preview modal + multi-type support; 2: review dev vs built work, resolve conflicts or close PR; 3: make PR 69 merge-ready; 4: fix blank PDF previews)
