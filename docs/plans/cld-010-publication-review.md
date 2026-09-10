# Publication implementation review

## Scope

Cloud and Foundry use separate simplicity and correctness passes. The final
correctness reviewers receive the code and saved plan, not the implementation
conversation. Production release checks remain separate from code review.

## Cloud simplicity

The independent reviewer checked 672f623 against 529d3cc. Commit 7a7fe93 applies
three reductions. Cleanup and intake tests returned 22 passed. Ruff passed.

| Finding | Disposition | Reason or evidence |
| --- | --- | --- |
| Remove the unused private-file digest field. | Applied. | Storage metadata still validates the digest before private access. |
| Remove the unreachable 120-second inspection delay. | Applied. | The third failed attempt is terminal. Delays remain 5 and 30 seconds. |
| Remove the cleanup candidate kind parameter. | Applied. | Its only caller creates object candidates. |
| Replace the roundtrip server's HTTP shutdown with process termination. | Retained. | On Windows, terminating the virtual-environment launcher left its child server running and prevented temporary-directory cleanup. Graceful shutdown fixed that observed failure. The route exists only in the test server. |

The reviewer retained publication records, immutable generations, retry leases,
cleanup evidence, the isolated parser, private access checks, and reply buffering
because they enforce accepted contracts. The final correctness findings follow.

## Cloud correctness findings

The fresh sol_high reviewer checked 7a7fe93 against 529d3cc. Three findings
require correction and recheck. The reviewed code is not ready for a PR.

| ID | Priority | Finding | Required correction |
| --- | --- | --- | --- |
| CR-001 | P2 | An inactive binding can consume retry attempts although it cannot upload. | Require and lock active binding authority before retry mutation. Recheck binding and tombstone on results. |
| CR-002 | P1 | Cleanup fails an abandoned staging file but leaves its publication uploading or validating. | Reconcile publication or message state after the cleanup transition commits. |
| CR-003 | P1 | PostgreSQL rejects locking across the nullable tombstone outer join. | Lock the publication row explicitly while retaining ancestry checks. Run all file lifecycle tests on PostgreSQL. |

The additional PostgreSQL publication run returned eight failed and five passed.
It confirmed the locking error in upload and retry paths. CI now includes all
file lifecycle tests on PostgreSQL, in addition to the concurrency tests.

Correction 6dddf82 passed 98 PostgreSQL file tests, with two platform skips,
and the full SQLite suite returned 848 passed and 31 skipped. The independent
recheck closed CR-001 and CR-003. A fifth expired lease remains discoverable
and is finalized by an active binding claim. These cleanup findings remain:

| ID | Priority | Recheck finding | Required correction |
| --- | --- | --- | --- |
| CR-002 | P1 | A lost post-commit reconciliation callback can still strand the publication. | Recover reconciliation from durable candidate state during replay or completion. |
| CR-004 | P1 | Retry can advance the generation before old staging deletion is confirmed. | Lock and check cleanup evidence. Keep the charge and defer retry until deletion is confirmed. |
| CR-005 | P2 | Retry locks account then file, but cleanup locks file then account. | Use a consistent lock order and test the concurrent PostgreSQL path. |

The separate Foundry reviewer performed this recheck because the tool could
not resume the original Cloud reviewer. This reviewer did not implement Cloud.

Correction 9725a14 replays reconciliation from the durable cleanup candidate,
blocks retry until deletion is confirmed, and uses Candidate, Account, then
File lock order. Owner retry schedules its scoped cleanup candidates before
the retry transaction. SQLite checks returned 26 passed. The PostgreSQL file
suite returned 99 passed and two skipped. Independent recheck is pending.

Recheck closed CR-002 and CR-005. It found that cleanup acceleration ran before
retry authorization. Correction 97b23f7 validates the failed state and current
revision before it schedules eligible candidates. The scheduling phase takes
no account or file locks. Its tests returned 26 SQLite and 32 PostgreSQL passes.
Final correctness recheck closed CR-004 and retained CR-005 closure, with no
P0-P2 findings. The separate final simplicity pass found
no removable machinery in Cloud 6dddf82 through 97b23f7.

## Foundry simplicity

An independent reviewer checked backend and runtime publication changes. A fresh
worker could not start because the tool reported its agent-thread limit. The
existing image reviewer therefore ran a separate read-only turn. That reviewer
did not implement the backend or runtime files. The final correctness pass must
remain separate.

| Finding | Disposition | Reason or evidence |
| --- | --- | --- |
| Remove unused publication-intent list routes and service helpers. | Applied in 900837a. | No production caller uses them. |
| Remove duplicate publication status helpers. | Applied in 900837a. | Current mutation paths already own these transitions. |
| Remove the due-publication cursor. | Caller corrected in 900837a. | Bounded pages must reach bindings after the first page. A two-pass test checks cursor preservation. |
| Remove the unused recovery-interval constructor parameter. | Applied in 900837a. | Recovery uses the existing interval constant. |

That commit also passes the publication identifier when it releases a ready
spool. Focused backend validation returned 56 passed. Runtime file tests returned
22 passed and one platform skip. Later failure tests passed the full runtime
coverage gate at 90.01%, with 708 passed and six skipped.

## Foundry correctness findings

The fresh sol_high reviewer checked 900837a against 0105a00, excluding the image
which has its own review. These findings require correction and recheck.

| ID | Priority | Finding | Required correction |
| --- | --- | --- | --- |
| FCR-001 | P1 | Local exhaustion permanently blocks later explicit Cloud retries. | Reopen local authority only for a newer Cloud retry revision and preserve the frozen manifest identity. |
| FCR-002 | P1 | Missing or corrupt spool data silently abandons a Cloud claim. | Report source_unavailable with the exact claim revision and lease token. |
| FCR-003 | P1 | A crash during ready-spool deletion can leave a permanent ledger charge. | Make release durable and complete an interrupted release during reconciliation. |
| FCR-004 | P2 | Exhausted intents and duplicate workspace rows can consume a wake page and skip remote bindings. | Exclude exhausted rows, deduplicate before the limit, and advance the remote cursor only for scheduled bindings. |

These IDs have an F prefix here to distinguish them from the Cloud findings.
The reviewer used CR-001 through CR-004 in the original Foundry report.

Backend correction 04f90e2 closed FCR-004. Recheck found that FCR-001 also
requires another claim at the same new Cloud revision after a local failure.
Correction b9f3af3 records the admitted Cloud retry revision and covers that
case. It also reports unavailable spools with the claim fence and completes
interrupted spool release from durable ledger state. PostgreSQL publication
checks returned six passed. Runtime checks returned 716 passed and six skipped,
with coverage at 90.02%. System and lint checks passed. Recheck is pending.
The extended cross-repository check passed after local exhaustion at five
attempts, an explicit Cloud retry, and a changed working file. It preserved
one model call, one execution, and the original bytes in generations 1 and 2.
The enhanced roundtrip also confirms that retry waits for old-generation
cleanup and that the final account has no reservation charge. It returned one
passed test in 7.70 seconds. Storage and inspection remain injected adapters.

The final recheck closed FCR-001, FCR-003, and FCR-004. It found that FCR-002
also needs a digest check for same-size spool corruption. Correction 88bfa97
checks the exact bytes before upload. The independent recheck closed FCR-002
with no P0-P2 findings. The separate final simplicity pass found no removable
machinery. The final runtime run returned 717 passed and six skipped, with
coverage at 90.02%. Backend validation and fresh PostgreSQL migration 0025
checks passed. The final cross-repository roundtrip returned one passed test
in 7.26 seconds at Cloud 97b23f7 and Foundry 88bfa97.

## Hermes image correctness

Commit b679105 addresses the three initial findings. A fresh sol_high reviewer
checked b679105 against aa2a979 and reported no verified P0-P2 findings. The review
covered default, wildcard, composite, refreshed, and deferred tool paths; private
context propagation and reset; tool-call identity; size and name bounds; and
service-account socket permissions. Pinned source patch application and Python
syntax passed. The actual image and service-account socket smoke require Linux CI.

| ID | Initial finding | Correction |
| --- | --- | --- |
| CR-IMG001 | Default, wildcard, or composite agents could expose private tools. | Private toolsets require explicit, mutually exclusive constructor capabilities. |
| CR-IMG002 | Ready names used a byte limit instead of the 255-character contract. | Ready-name validation counts characters and retains unsafe-name checks. |
| CR-IMG003 | The socket smoke did not prove the runtime-to-Hermes UID/GID boundary. | A fresh-volume check uses the actual UID 10000 account and supplementary GID 10001. It checks connection and denied directory mutations. |

## PR CI and automated review corrections

Cloud PR 39 passed Linux Django and PostgreSQL checks at ddbdff5. General
review found that failed file-message retries lose attachments or reject empty
text. Corrections through ae3ad66 retain ordered ready files and accepted-file
access. They preserve the existing one-retry and first-turn bootstrap contract.

| Retry finding | Final disposition |
| --- | --- |
| Expanded retry chains break bootstrap behavior. | Closed: retain the existing single-retry rule. |
| File locks need a stable order. | Closed: lock by UUID and preserve manifest position order. |
| Ordinary sends can replay a retry key. | Closed: duplicate intent must have the same retry lineage. |
| An Ally tombstone must deny new file retries. | Closed: lock Ally before Conversation and deny before message or outbox creation. |

Independent correctness and a separate simplicity pass closed all four findings
at ae3ad66 with no new P0-P2 issues or required cuts. Full validation at 26d1ac9
returned 851 passed and 32 skipped, with 90.14% coverage. The final correction
passed 37 focused tests, system checks, migration drift, and Ruff. Current-head
Linux CI remains required.

Foundry PR 54 exposed two Linux CI issues. Commit 149962d adds the source
import path for the build-time smoke. Commit e57bc69 keeps admitted private
control tools direct when generic tool-search assembly would defer them.
Its source smoke covers default, all, composite, exclusion, and mutually
exclusive capabilities. Commit eaf9d07 fixes the unprivileged test setup
without changing production root ownership or 0700 permissions. Its separate
ownership failure tests remain active on POSIX. The test-only correction
passed independent combined review.

Enkii identified four additional Foundry findings:

| Finding | Correction | Validation |
| --- | --- | --- |
| P1: Django's default body limit rejects valid 25 MB uploads. | 6c1c497 reads at most 25 MB plus one byte and retains service validation. | API checks accept 3 MB and 25 MB, and reject a bounded read from 30 MB. Nine backend tests passed. |
| P2: Cleanup failure drops an already-ready tool result. | 6c1c497 retains the ready result when local release fails. | Both filesystem and fenced-spool failure variants pass. |
| P1: Forged ledger paths can escape the cleanup root. | 6a58103 validates canonical publication UUIDs and profile path components at ledger read. | Copying and releasing traversal, absolute-path, and wildcard cases stop before deletion. |
| P1: A removed profile can stop recovery. | 6e1e005 handles ProfileStoreError at tool and recovery boundaries. | The tool returns a safe failure and the worker advances to the next profile. |

The separate simplicity pass accepted the production corrections and removed
an unnecessary test import in e57bc69. Independent correctness recheck through
6e1e005 found no actionable P0-P2 issues. Image and removed-profile simplicity
checks found no removable machinery. The final runtime run returned 736 passed
and eight skipped, with coverage at 90.04%. A new review worker could not start because the tool reported its
agent-thread limit. The existing independent simplicity reviewer therefore
performs a separate correctness turn; that reviewer did not implement these
changes. This does not replace Linux CI or the current-head automated review.

Linux image CI at 6e1e005 passed the complete build and smoke sequence,
including the publication tool and service-account socket boundary. Runtime
CI reached 90.13% coverage but found four tests without the explicit ownership
fixture. Test-only correction bc99a67 adds that fixture, passes 23 focused
tests and independent combined review, and is pushed for final Linux CI.

At bc99a67, Linux CI passed 649 backend tests and 742 runtime tests, with
90.27% runtime coverage. Image build and all smoke checks passed. Automated
review then identified the writable ledger/lock location and uncaught bridge
startup errors as P1 findings. Their correction and recheck remain active.

## Subsequent PR review

Cloud Linux CI at 8df72f3 passed 854 tests, 105 PostgreSQL file tests,
40 concurrency tests, and two schema tests, with 90.14% domain coverage.
Automated review found four further cases. Correction 6e613db rebuilds a
queued outbox after attachment removal, replaces incomplete terminal file
paths with the failure notice, avoids file queries for ordinary text deltas,
and limits preview parsing to 20 requests per minute per file owner. Tests
cover a queued two-file message that is removed and re-armed, partial path
variants, zero-query text chunks, rate rejection, and throttle failure.
Validation returned 38 passed and one skipped. Independent recheck is active.

Foundry 6402229 and 05439c7 set the persistent volume parent to root-owned
01777 after bootstrap and test model-user writes and denied metadata removal.
Runtime correction 2fd8b61 moves the ledger and lock into a protected directory,
rejects untrusted state, and disables publication after startup failure while
other claims continue. Local runtime tests passed, but coverage was 89.80%.
Review found remaining legacy-spool promotion and stale reconciliation races;
those corrections remain active. Linux image and runtime checks must rerun.

Cloud recheck found that removing an unclaimed outbox must return its targeted
routine-result context to pending state. Correction 914a00f does this within
the existing transaction. The regression confirms that the rebuilt command
contains the context once and consumes it again. Preparation and routine-result
checks returned 23 passed. Independent correctness and simplicity rechecks
approved 8df72f3 through 914a00f with no remaining findings.

Foundry final recheck approved 98c4f30. Correction 1b6a5ac rejects untrusted
legacy spool ownership without promotion and revalidates discovered manifests
under the ledger lock. This closes the release/reconcile capacity race. Full
runtime validation returned 745 passed and eight skipped at 90.00% coverage.
The clean dev merge preserves file gates and runtime behavior. It passed 61
routine/release/file tests and nine publication tests. Linux CI is active.

Cloud policy review at 38498eb found two P2 cases. Correction 949e879 permits
promotion while sibling publication files upload, with all existing file,
generation, lease, scope, and tombstone checks retained. It also applies
case-insensitive path checks to stream holds, lookup guards, and terminal
flushes, and emits canonical ready paths. Validation returned 39 passed and
one skipped. Independent correctness and simplicity review approved the change.

Cloud general review could not publish because GitHub returned an internal
422 error. The completed run identified the promotion filter and preparation
recovery page. Root confirmed that the oldest unchanged pending or failed
messages can fill every recovery page. Correction da34cc4 selects only active
file transitions before applying the page limit. It retains the non-empty
active-file requirement and all reconciliation locks and fences. Fourteen
preparation tests passed, including a limit-one starvation regression.

Foundry Linux image CI at 98c4f30 passed the actual protected-volume smoke.
Runtime CI found 13 Linux-specific failures in cleanup and test ownership
setup. The correction remains active; the CI result is not a pass.

Independent correctness and simplicity rechecks approved da34cc4. No additional
findings remain in the locally reviewed Cloud corrections.

The delayed Cloud general-review comments later became visible despite the
posting error. They identify ready armed messages without outboxes after gate
enablement, in addition to interleaved promotion. Correction 1136188 includes
those messages only when the existing delivery gate is enabled. Reconciliation
then uses the existing idempotent dispatch path. Fourteen preparation tests
passed, including no work while disabled, one recovered outbox after enablement,
and no second recovery on replay. The separate starvation correction remains.

Foundry 2eb7021 keeps feature-disabled cleanup working when no publication
state exists. Existing spool or journal state still requires the protected
boundary. Linux-specific test setup uses explicit ownership seams. Full local
runtime validation returned 746 passed and eight skipped at 90.02% coverage.
Independent recheck remains required before publication.

Independent correctness and simplicity rechecks approved Cloud 1136188.


## Final code validation and branch rename

Foundry 12f0dc5 adds the explicit protected-volume check before bridge startup.
Invalid ownership or mode disables publication before state or socket creation;
other worker claims continue. Independent correctness and simplicity reviews
approved 2eb7021 and 12f0dc5. Local validation passed 748 runtime tests with
eight platform skips and 90.01% coverage. Linux CI passed 659 backend tests,
754 runtime tests, 90.01% coverage, and the complete image build and smoke
sequence. The protected-volume checks ran in that image. Security and policy
reviews at 12f0dc5 are clear; the general review remains in progress.

Cloud 6f760fd passed all three automated review lanes. CI passed 866 tests,
110 PostgreSQL file tests, 40 concurrency tests, two schema tests, and 90.14%
domain coverage. The cross-repository check passed in 9.59 seconds against
Foundry 12f0dc5, with one model invocation and zero final reservation charge.
It uses injected storage and inspection adapters.

The requested Cloud branch rename is complete: `ft/cld-010-file-sharing`.
GitHub closed PR 39 during the rename. Replacement PR 40 contains the same
commits and links the prior review history. Foundry PR 54 remains open.
Final PR checks must pass after this documentation update. No merge or
deployment is authorized. Production file gates remain disabled.


## Replacement PR correction review

PR 40 general review found account lock order and missing preparation tombstone
checks at 0317988. Corrections a831e51 and 010d764 close those findings and the
related deletion races found by independent review. Retry and deletion now use
Account, Ally, then Conversation order. Deletion locks conversations in ID
order before the tombstone is written. Dispatch locks joined Message queries
only on the message row and checks the tombstone under the conversation lock.
Queued or expired eligible outboxes terminate with ally_deleted. The locked
query rechecks status, due time, and lease with the existing due predicate.

Simplicity review found one 12-line reduction; 010d764 applies it. Correctness
review approved that head with no remaining findings. Validation passed:
59 focused tests; 212 file/chat PostgreSQL tests with two platform skips;
34 final PostgreSQL dispatch/preparation tests after the simplification;
25 dispatch tests; make check; make lint; and git diff --check. The final
cross-repository roundtrip passed in 6.48 seconds before the predicate-only
simplification, with one model invocation and zero final reservation charge.

An external request claimed before deletion can already be in flight. No
database transaction spans that call. Accepted-file reads still deny access
after the tombstone. Final PR checks remain required after publication.
