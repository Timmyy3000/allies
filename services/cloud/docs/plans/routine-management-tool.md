# Routine management from Ally chat

Route: fast. Owner: Cloud for product state; Foundry for execution authorization.
Implement personally with Ponytail; no new scheduler, service, dependency, or UI.

## Boundary

A Hermes `allies_routines` tool calls a Foundry endpoint with a short-lived,
attempt-bound capability. Foundry checks the live attempt, lease, generation,
and profile, then forwards trusted execution/message identity to Cloud using
the existing service authentication. No service credentials or owner IDs are
model arguments. Routine runs cannot create other routines.

Cloud resolves the original dispatched message, current binding, personal
workspace owner, and membership. Reuse routine management and discovery.
Serialize each message's tool calls and persist exact responses keyed by call
identity with a request digest. Conflicting replay fails without mutation.
Deletion requires an opaque challenge issued in an earlier conversation turn.
Never infer confirmation from the tool's boolean assertion alone.

Expose create/list/inspect/update/pause/resume/request_delete/delete. Supply
browser timezone and current time as context; ask when timing is unresolved.
Disable hosted local cron. Confirm mutations only after a saved receipt.

## Validation and rollout

Test cross-workspace and wrong-binding rejection, expired attempts, replay,
same-turn delete rejection, CAS conflicts, tool isolation between concurrent
sessions, and absence of hosted cron. Exercise actual chat creation, scheduled
dispatch, separate execution, and main-chat result using local services.
Run repository Django checks, migrations check, Ruff and affected pytest suites;
build/smoke the derived Hermes image. Review correctness and simplicity directly.
Open coordinated PRs; deploy Cloud before Foundry/runtime images. Rollback the
tool integration without dropping saved routines or the scheduler.

Keep mobile held. Staging verification requires merged/promoted changes; do not
represent a local test as deployed proof.

## Delivery evidence — 2026-09-10

Cloud matches the retained dispatch fingerprint, not command bytes (which are
erased after acceptance). Browser timezone is persisted on each message and
preserved for retries. The internal endpoint requires existing Foundry service
authentication; live lease authorization stays in Foundry.

Full Cloud suite: 756 passed, 24 skipped. Django/system and migration checks,
changed-file Ruff, and diff checks pass. Direct correctness review covered scope,
revocation, retries, deletion confirmation and timezone; direct simplicity review
kept the existing scheduler and management services. No unresolved P0–P2 finding
in this slice. No independent reviewer was delegated, per owner instruction.

Docker/PostgreSQL proof used the actual built Hermes tool bridge, Foundry HTTP
capability endpoint, Cloud HTTP endpoint and scheduler, runtime result parser,
Foundry event publisher, and Cloud main-chat insertion. Creation and same-call
replay produced one routine; a one-time occurrence ran in a separate conversation
without management authority; its result was inserted into the main conversation.
The proof caught and fixed a Foundry/Cloud workspace-ID mismatch in result scope.
Inputs and business outcome were scripted; no real model or staging proof claimed.

## Enkii finding disposition — 2026-09-10

The reported concurrent duplicate insert race is not reachable on PostgreSQL:
the atomic adapter locks the parent Message row before reading or creating any
tool receipt. Same-message requests serialize on that lock. A real PostgreSQL
two-thread duplicate test returns identical receipts and one routine/receipt row.
Do not add an IntegrityError catch that obscures this existing serialization.

The reported timezone-only dispatch overflow is also not reproducible for admitted
messages: admission checks UTF-8 bytes against 16,000, below the 16,384-byte command
limit, leaving room for the timezone block. A maximum-size multibyte message test
passes with timezone context. Existing routine-result-context budget behavior is
unchanged. All 10 tool tests pass on local Docker PostgreSQL. Direct correctness
and simplicity review retained the implementation and added these boundary proofs.
