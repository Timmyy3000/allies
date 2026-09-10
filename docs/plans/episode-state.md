# CLD-010 implementation

## Identity
- Objective: Complete the accepted Cloud and Foundry backend implementation and prepare separate PRs into dev.
- Repositories: Allies Cloud and Allies Foundry. Interface implementation follows later.
- Worktree: `C:/Users/ASUS/Desktop/projects/allies-cloud/.forest/worktrees/ft/cld-010-planning`.
- Foundry worktree: `C:/Users/ASUS/Desktop/projects/allies-foundry/.forest/worktrees/ft/fnd-011-file-sharing`, branch `ft/fnd-011-file-sharing`, base `1d03ea557be757f4eca4c6b6478d542291169b14`.
- Branch: `ft/cld-010-file-sharing`. The existing worktree directory is retained.
- Intended base: `dev`.
- Route: full. File authorization, immutable versions, cancellation races, storage, and cross-repository contracts require a full plan.
- HTML required: yes, per the user's supplied repository instructions. Keep complete Markdown and HTML in sync.
- Scope: Approved Cloud and Foundry implementation. Interface implementation remains later.
- Plan: `docs/plans/cld-010-file-sharing.md` and matching `.html`.

## Current State
- Phase: Fix the six independent attachment-review findings on PRs 40 and 54.
- Status: Corrections and current-dev integration validated locally; current-head hosted checks and Enkii v1.2.0 reviews pending.
- Scope confirmed by the owner: Cloud and Foundry first, Interface later; keep document intake and existing Office-preview exclusions. Use Ponytail full for lean fixes. No merge, deployment, or feature enablement.
- Worktrees: local isolated Git worktrees for the existing PR branches; retain through review.
- Implementation: orchestrator-owned; this correction shares cleanup/lock and publication contracts. The historical named implementation worker is unavailable in this harness; auto delegation is not used.
- Review: separate Ponytail simplicity and independent correctness passes.
- Plan: use the accepted backend plan; this is a focused correction, no new visual review artifact.
- Steps: (1) commit retry cleanup, release the queue on cancellation, and release abandoned reservations; (2) reconcile frozen publications and preserve partial-retry eligibility; (3) align continuity launch with protected volume ownership; (4) regressions, integration validation, publish existing PR updates and inspect CI.
- Acceptance: each reported failure has a regression; preserve scope, leases, immutable bytes, account-before-file lock order, and no additional model calls during recovery.
- Validation: locked uv environments; focused file/chat and runtime publication/continuity tests, Django checks/migration drift, Ruff, full relevant suites, PostgreSQL checks where available, cross-repository recovery harness, then current-head CI.
- Rollback: revert only correction commits; retain data, migrations, frozen files, and disabled release gates.
- Last transition: 2026-09-10.

## Current validation and delivery record

This section supersedes the historical entries below.

- Owner followup: attachment flags default on; environment overrides explicitly disable them. Ordinary defaults are 10 GB workspace storage, scanner port 3310, and a 120-second upload lease. External storage/scanner connection details remain required. Production release checks remain independent, with explicit shutdown overrides in the deployment template; deployed variables were not changed.
- Defaults correction validation: Cloud 890 passed / 37 skips; Foundry 668 backend passed / 13 skips and 790 runtime passed / 8 skips, 90.37% runtime coverage. Nonroot publication bridge startup returns unavailable before creating shared state; the regression and real Linux nonroot smoke passed. Independent Cloud recheck is clear. The accepted configuration convention is recorded in the canonical Nabu file specification.

- Corrections: committed retry cleanup, cancellation queue release, abandoned reservation accounting, initial publication/spool reconciliation, partial retry eligibility, and continuity launch ownership. Review followups cover multiple staging objects, failed obsolete-object deletion, bounded registered wakes, and exhausted explicit retries.
- Integrated current dev in both PRs. Merge migrations preserve both histories. Routine tools and file publication coexist; the Hermes routine overlay was rebased on the preceding file overlays.
- Cloud implementation 182d0c4: 888 passed / 37 platform or backend skips; PostgreSQL file suite 121 passed / 2 skips; fresh PostgreSQL migrations, system/drift, lint, and formatting checks pass. Final formatting-only normalization follows this record.
- Foundry Python implementation d00dc80: full validation passed, 665 backend tests / 13 skips and 787 runtime tests / 8 skips; runtime coverage 90.33%. PostgreSQL publication/file regressions: 15 passed; fresh migration application passed.
- Cross-repository API/HTTP roundtrip passed on integrated sources with one execution, one model invocation, cleanup before retry, and identical frozen bytes in both generations after the working file changes.
- Hermes image built from the pinned base with all overlays and build-time smoke checks. The final image also passed the publication capability smoke. This is local verification, not a deployment or a production storage/ClamAV proof.
- Ponytail simplicity and independent correctness reviews closed the six original findings and followup state/lock issues. The integration review identified the overlay conflict; its correction is included before publication.
- Per owner request, both workflows pin Timmyy3000/enkii@v1.2.0. Hosted current-head review/CI must finish before readiness is claimed.
- Existing PRs remain Cloud #40 and Foundry #54 into dev. No merge, deployment, feature enablement, Interface, or Nabu mutation. Office document collection remains accepted; Office previews remain excluded.
- Retain isolated worktrees under helpers/.tmp/attachment-fixes-cloud and attachment-fixes-foundry through review. Existing review monitor remains paused; this active task owns checks. No new recurring automation requested.

## PR size decision

Keep one backend PR per repository, as authorized. Both exceed the normal size
target. The Cloud file state, byte intake, inspection, access, and cleanup must
share the same fences. Foundry staging, frozen publication, recovery, and the
image tool must share the same authority contract. Separating these into PRs
that all target dev would expose incomplete intermediate behavior or require
overlapping changes. Keep the disabled production gates and the focused commit
history. Review the contracts, state transitions, runtime, image, and failure
tests as separate sections. The delivery owner must reassess this choice if a
review identifies an independent change that can be removed safely.

## Resumption evidence
- The user requested completion in task 01a08856-4559-7df1-9544-c29868f8f714 and retained the linked task's authorization to implement and open PRs. No merge, deployment, Interface work, or Nabu mutation is authorized.
- The saved scoped profile was reloaded on 2026-09-09. Its current-user-only Windows DACL was checked. Authenticated tree returned 200. Scope is projects/allies with read/write permission; expiry is 2027-03-06T15:33:17.700Z. No invite was redeemed.
- Remote MCP tools/list and read_note succeeded. Index revision: b3daafe780ee741ba6032f382ac5b426fc3d7fe6c2496d094d2e2eae061028ce. CLD-010 revision: a00fcf52d642e995720d2886927cfad7766837cfd9d7846049b9d0b92a3eefb9. Specification revision remains e8a30bf1eb812c614f4a00c815e6486749bcdec4f9ea26ce9b77731f5f18fa46. FND-011 revision: 890285542660b004c0af9e65953eca11ec0dbd4dd9133b2f20747f9a475bece5.
- Fetched Cloud dev is 90a1ca8; Foundry dev is 70a2080. Both include routines. Cloud merge-tree reports one API registration conflict; Foundry reports no textual conflicts. Semantic integration needs validation.
- Current user-supplied instructions select terra_xhigh for implementation and fresh sol_high sessions for reviews. These override historical worker selections below. Implementation delegation is enabled.
- Historical no-push/no-PR statements below describe earlier scope; the later user authorization permits feature-branch pushes and PRs into dev.
- Integration commits: Cloud 875df52 and Foundry 231da4c. The Cloud API conflict retains both file and routine registration. Both merge commits preserve the existing feature work.
- Integrated baseline: Cloud files/chat/allies/config tests returned 387 passed, 9 skipped, and one routines fixture hash failure. Foundry file/routine contract tests returned 58 passed and one matching hash failure. Windows checkout had converted the hash-locked routine document and fixture to CRLF. Restoring canonical LF bytes produced no Git content diff; affected Cloud tests then returned 7 passed and Foundry tests 8 passed.
- Both backend lock checks, Django system checks, and migration-drift checks passed. A fresh temporary Cloud SQLite database accepted all migrations and passed migrate --check. The inherited development database was not changed. This is not PostgreSQL race evidence.
- Shared file execution fixtures remain byte-identical at SHA-256 A2D91FB63E3CD5FDC15602107FBF98E4F266257AD567BA697FED9F5EB2C2C903.
- uv 0.12.3 is installed outside PATH. Commands can add its Scripts directory to process-local PATH; global configuration is unchanged.
- The inbound workers confirmed the full mounted accepted-file path: /api/v1/internal/v1/accepted-files/{file_id}/content, with binding_id and message_id query parameters. This is the accepted relative route under the existing API mount.
- A disposable PostgreSQL 17.11 cluster runs on loopback port 55439 for this task. Cloud and Foundry have separate synthetic databases. The binaries and cluster are under the task-specific temporary directory allies-cld010-postgres17. Stop this cluster and remove only its verified task directory at closeout. No existing host database or service was changed.
- Inspection helpers: 41198fc adds five bounded helper/test/operation files. Independent simplicity review found four reductions; 9a15eb8 applies them and removes 50 net lines. Parent verification: 10 focused tests and Ruff pass. Separate correctness review is in progress. Legacy Office parsing and isolated PDF/HEIC previews remain explicit gaps.
- Active inbound packets own separate Cloud and Foundry code. The parent owns the shared documents and integration. A global development switch is not negotiated runtime capability; do not add a binding allowlist as a substitute. Production file dispatch must remain blocked until generation/release-aware capability proof is resolved.
- Cloud inbound commit 529d3cc passed make check, make lint, file tests (38 passed, 2 skipped), chat tests (93 passed, 4 skipped), and six PostgreSQL race tests. It includes durable draft recovery, exact frozen outbox manifests, and accepted-file access during receipt uncertainty.
- Foundry inbound commit 2c2723e passed 252 runtime tests and 50 backend tests with PostgreSQL. It stages the complete manifest before model invocation and preserves edited working copies on replay. Both repositories use the established Authorization Bearer event-service boundary.
- Inspection correctness review identified five defects: unbounded seekable reads, incomplete Office validation, permissive scanner verdicts, uncaught image-limit warnings, and platform-dependent path checks. Commit 20ee33b corrects these cases. Parent verification passed 24 tests and Ruff. Isolated worker and live scanner proof remain required.
- Foundry image check found invalid incoming patch hunk counts. Commit b2d5fc6 corrects them and adds an image smoke script. The complete overlay chain applies to pinned Hermes source 36cb5ae; Python compilation and extracted source-function checks pass. No complete container build has run.
- Separate terra_xhigh workers now own Cloud publication/private access/inspection tasks/cleanup and Foundry publication intent/spool/tool/recovery. A fresh sol_high worker reviews the stable inbound commits for simplicity.
- Foundry simplicity correction 0105a00 passed 129 affected runtime tests in parent verification. Review dispositions are in cld-010-inbound-review.md. A fresh coordinated correctness review is active.
- Temporary verification tools also use allies-cld010-hermes-source and allies-cld010-gitleaks under the current-user TEMP directory, plus six allies-cld010-*.patch copies. Remove only these exact task resources after workers finish using them.
- Cloud 6b85ae7 adds publication reservation/status/retry and inspection tasks. It passed 34 focused tests, Ruff, system checks, and migration-drift checks. Private opening and cleanup remain active work.
- Cloud b410399 adds the isolated parser adapter and pure type policy. Parent tests passed 33, with one POSIX process test skipped on Windows. The Cloud worker must connect the default task path and align inspection leases with the bounded process duration.
- The fresh inbound correctness review found seven cases. See cld-010-inbound-review.md. Both implementation workers own the corrections and regression tests. The prior five inspection-helper defects passed the fresh recheck.
- Foundry d9d4176 and e5ce860 align the image's name limit with 255 characters and measure JSON context in UTF-8. Pinned source-function smoke checks pass, including ten long Unicode names.
- A separate terra_xhigh image worker owns the synchronous publish_files tool and private context hook. The runtime worker owns the local socket server. Publication must freeze during the tool call, not after the model turn.
- Cloud ab76c1b adds isolated preview decoding. The focused helper suite passed 35 tests; two real POSIX process tests require Linux.
- Foundry 8b17e7a adds the synchronous Hermes publication tool. A fresh image review found three defects: default-agent tool exposure, inconsistent Unicode name limits, and missing service-identity socket proof. A separate implementation worker owns these corrections.
- Foundry 2794a1e and 165290a add bounded publication wake discovery, spool reconciliation, partial cleanup, polling, and frozen recovery. Worker checks passed 56 backend tests and 144 runtime tests, with one platform skip.
- Cloud 23ee2e9 preserves the cross-repository publication check in scripts/file_roundtrip. The runtime worker used real Foundry API routes and Cloud HTTP routes. After a failed inspection and completed model attempt, recovery reused the frozen bytes after the working file changed. The check passed with one model call, one execution, one intent, and upload generations 1 and 2. It injects scanner results, private in-memory storage, and the exact test loopback URL; it does not prove deployed storage, TLS, or ClamAV.
- That roundtrip exposed two Cloud API defects that direct service tests missed: retry claims omitted file size, and HTTP lease tokens were compared as strings against UUID values. The Cloud worker corrected both and added API regression tests.
- Foundry full runtime validation found an old composition test fixture without the new optional bridge field. Commit 66187f3 updates the fixture; all seven composition tests pass. The full repository validation is active.
- Fresh review creation reached the tool's agent-thread limit. The existing independent image reviewer has a separate read-only turn for Foundry backend/runtime simplicity. This reviewer did not implement those files. Required correctness review remains separate.

## Decisions
| ID | Decision | Source | Affected phases |
| --- | --- | --- | --- |
| D1 | Use Astra with low reasoning for planning. | User | Planning |
| D2 | Use Astra with low reasoning for each independent review. | User correction, 2026-09-08 | Plan review |
| D3 | Save Terra with high reasoning for future implementation. | User | Implementation |
| D4 | Keep the existing isolated Forest worktree. | Kickoff setup | All |
| D5 | Plan Cloud and Foundry implementation together for the Terra high implementation worker; coordinate Interface implementation later. Preserve separate repository contracts and PRs. | User voice correction, 2026-09-09 | Planning, reviews, later implementation |
| D6 | Accept the combined backend plan and authorize implementation after fetching every Cloud and Foundry worktree. Preserve unrelated dirty worktrees. | User, 2026-09-09 | Implementation |
| D7 | Keep `file_input_v1` as a disabled admission seam until the later Cloud readiness and ancestry gate can safely project file descriptors. | Code review CR-003, 2026-09-09 | Cloud Phase 2 |
| D8 | Reject and revert the incomplete Cloud Phase 2A upload API. It must not expose uploads until the complete admission safeguards are implemented and reviewed together. | Code review CR-001 through CR-006, 2026-09-09 | Cloud Phase 2 |
| D9 | Keep the reviewed Cloud admission endpoints permanently disabled in production until inspection, serving-boundary streaming controls, capacity approval, and deletion integration are complete. | Correctness review CR-002/CR-003, 2026-09-09 | Cloud Phase 2 release |

## Evidence Index
- Nabu source: `projects/allies/index.md`.
- Ticket: `projects/allies/delivery/tickets/cloud/CLD-010.md`.
- Both notes were read after successful scoped credential renewal.
- Source snapshots: `docs/plans/cld-010-sources.md` contains the approved specification, Delivery Now, FND-011, and INT-106.
- Foundry ticket refreshed on 2026-09-09: `docs/plans/cld-010-foundry-source.md`.
- Worker selectors: `docs/plans/kickoff.yaml`.
- Skill update: Nine global skills updated; `npx skills check` reported all global skills current. Ponytail was refreshed at 4.9.0. Bundled skills remain app-managed.

## Validation
- Nabu access was renewed and verified on 2026-09-08. The saved credential has current-user-only access permissions.
- No product code changed. Product tests have not run.
- Prior Cloud-only independent adversarial review: Ready. ADV-001, ADV-002 and ADV-003 resolved and independently rechecked. Expanded scope needs a new review.
- Prior Cloud-only independent simplicity review: Lean, no required revisions. Expanded scope needs a new review.
- Prior Cloud-only Better Docs and Humanizer applied to the complete draft. Original and editorial diff are preserved. Inline code, numbers and headings are unchanged by editing.
- Prior Cloud-only Markdown/HTML parity: 406 content blocks, 11 tables, embedded source and SHA-256 verified. No missing blocks or foreign identity nodes.
- Prior Cloud-only browser checks: desktop light and mobile dark, no page overflow; table regions support horizontal scrolling. The skip link is visible and reachable on focus.
- Lavish audit reported only its offscreen skip-link warning. A direct focus check confirmed the link is accessible; this is not an unreachable control.

## Delivery And Closeout
- PR and monitor: Not started. This is the first reviewed implementation slice; no push, PR, deployment, or Nabu mutation is authorized yet.
- Worktree: Retained for continued planning.
- No push, deployment, or Nabu note change occurred. The invite was redeemed to renew access.

## Metrics
- Planning worker: Astra low; initial draft, sibling-evidence refresh and review corrections complete.
- Adversarial review: Astra low; initial review and two focused rechecks. See `cld-010-adversarial-review.md`.
- Simplicity review: separate Astra low worker, complete. See `cld-010-simplicity-review.md`.
- User correction count: 3, review worker selection, combined backend scope and remote synchronization. Expanded reviews are complete.

## Repository synchronization
- User authorized remote updates on 2026-09-09. Clean main dev checkouts fast-forwarded: Cloud dd8bba6, Foundry 1d03ea5, Interface f21e5ff. All matched origin/dev (0 ahead, 0 behind).
- Planning worktree bases match those fetched development refs. Existing planning edits were preserved.
- Before implementation, `git fetch --prune origin` completed for Cloud and Foundry. Every worktree was inspected; only the two CLD-010/FND-011 target worktrees are used, and both are clean.
- Open routines work overlaps Foundry execution/claim/worker paths and Cloud API/settings registration. See the master plan coordination section. No open Interface PR was returned.
- The committed Cloud planning branch merges cleanly in a non-mutating merge-tree check with the remote routine-management branch. This does not prove that future implementation is conflict-free.

## Combined backend handoff
- Final adversarial review: Ready. BADV-001 through BADV-003 resolved and rechecked.
- Final simplicity review: Lean. No required revision.
- Better Docs and Humanizer complete; latest source and diff preserved. Matching HTML verifies 524 blocks and 14 tables; desktop/mobile layout and focused skip link verified.
- See cld-010-validation.md and the backend adversarial/simplicity reports for current evidence. Earlier Cloud-only metrics above are historical.
- Cloud and Foundry worktrees are retained for the later implementation worker. Interface remains later. No feature code, infrastructure provisioning, push or PR was performed.
- The user accepted the plan and authorized implementation on 2026-09-09. The next delivery state is implementation, then separate review and PR readiness for each repository.

## Foundation implementation evidence
- Cloud commits: `7e19499` adds the file-domain/contract foundation; `1c1866d` removes redundant constraints; `2d467d1` enforces aggregate and optional-manifest bounds; `e8566f8` removes the no-op app configuration; `620292a` pins file-bearing command fingerprints.
- Foundry commits: `816ce01` preserves the optional manifest through execution/claim state; `12a9128` enforces the same manifest bounds; `ef4c25b` pins the matching fingerprints.
- Independent simplicity review removed 50 lines across two passes. Independent correctness review found CR-001 through CR-004; all are resolved. The accepted heads are Cloud `620292a` and Foundry `ef4c25b`.
- Orchestrator validation passed: Cloud system check, migration drift check, and 27 focused `files`/dispatch tests; Foundry system check and 47 runtime contract tests. The shared golden fixture SHA-256 is `A2D91FB63E3CD5FDC15602107FBF98E4F266257AD567BA697FED9F5EB2C2C903`. `uv` is absent from PATH, so Make targets were not used; both locked virtual environments were present and ran the equivalent direct commands.
- The Phase 1 disabled-admission boundary remains intact. No storage I/O, file API, staging, publication, recovery, Interface, deployment, push, PR, or Nabu change was made.
- The later Phase 2A attempt added an upload API but its independent review found unsafe request buffering, unavailable production configuration, missing rate/queue/quota admission, unrecoverable receiver states, premature ready promotion, and Interface-contract drift. Commit `54099c3` non-destructively reverts those two Phase 2A commits. Cloud `backend` exactly matches the accepted foundation after the revert; Django system/migration checks and 27 focused tests pass. A pre-existing import-order warning in the restored foundation test remains unchanged.
- Cloud commits `cc1c2cc`, `6de4187`, and `cfba20d` add the gated reservation and raw-byte intake boundary. They use bounded 64 KiB streaming, exact content length, a 25 MB file limit, private object metadata, scoped accounting, queue and rate controls, writer fences, verification before ready, and documented response contracts. The path stops at `validating`; it does not dispatch, retrieve, publish, or call Foundry.
- A fresh simplicity review identified three safe reductions. Commit `6de4187` applies all three. A fresh correctness review found CR-001 through CR-007. Commit `cfba20d` resolves them. A second fresh correctness review found no actionable P0, P1, or P2 findings.
- Direct final validation passed: Django system check, migration drift check, Ruff check and format check, `git diff --check`, and 108 focused files/chat/config tests. The implementation worker also ran the full suite: 678 passed and 23 skipped. PostgreSQL-specific tests remain skipped because no PostgreSQL connection is configured locally.
- The source migration graph is clean. The inherited local SQLite history still records the two pre-squash, unshipped migration names, so it was not rewritten or used for `migrate --check`. A fresh CI or PostgreSQL migration apply remains required. Nabu was not refreshed during final review because the configured request returned 401.


## Replacement PR review correction

Cloud PR 40 at 0317988 passed CI, security review, and policy review. General
review found two P2 defects in preparation.py: retry acquires the workspace
account lock after message/file locks, and preparation scope omits the Ally
file tombstone. The implementation worker owns scoped fixes and regression
tests. The task PostgreSQL cluster was restarted for real row-lock checks.
Foundry PR 54 at 12f0dc5 has passed all checks and all three review lanes.

The first correction a831e51 passed 38 preparation/dispatch tests, 110 file
tests on PostgreSQL with two platform skips, and 41 PostgreSQL concurrency
tests. The cross-repository check passed in 6.93 seconds. Simplicity review
was clear. Correctness review found remaining retry/tombstone lock ordering
and tombstoned file dispatch cases. The worker is extending the same scoped
correction. The review monitor is paused in the app; the active owner continues
the delivery loop. No ready-to-merge claim applies to Cloud until these pass.

## Final deletion correction

Cloud a831e51 and 010d764 use the account before Ally and conversation locks
for retry and deletion. Deletion locks all affected conversations in ID order
before it creates the tombstone. Preparation denies tombstoned scope. Dispatch
locks only the selected message row, then checks deletion under the existing
conversation lock. Queued and expired-lease rows for deleted Allies terminate
with ally_deleted after status, due time, and lease are revalidated. Completed
rows and newer active leases are not overwritten.

A request claimed before deletion can already be in flight. This correction
does not hold database locks across that network call. Accepted-file reads
still deny access after the tombstone. Production release gates remain off.

Validation before the final predicate simplification: 59 focused tests,
212 file/chat tests on PostgreSQL with two platform skips, make check, and
make lint passed. The cross-repository roundtrip passed in 6.48 seconds with
one model invocation and zero final reservation charge. Simplicity review
identified a 12-line reduction: reuse the existing due predicate in the locked
outbox query. It was applied in 010d764; all 25 dispatch tests and Ruff passed.
Independent correctness recheck approved 010d764 and closed both findings. The final PostgreSQL dispatch and preparation suite passed 34 tests in 28.33 seconds. Final GitHub checks remain required after publication.

## Enkii P2 correction

- Publication reservation now locks the workspace storage account before the
  publication scope locks. The scope keeps the Ally, Conversation, and Message
  order.
- Removing a READY inbound file now records the existing cleanup intent in the
  same transaction. A rollback records nothing. Repeated removal repairs a
  missing candidate when the file is unprotected.
- Focused local validation passed: 43 preparation, publication, and cleanup
  tests; Django checks; migration drift check; Ruff; format check; and diff
  check. The PostgreSQL preparation module passed 10 tests in 26.59 seconds.
