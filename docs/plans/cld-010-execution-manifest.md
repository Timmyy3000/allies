# CLD-010/FND-011 Execution Manifest

## Shared Context

- Work brief: `docs/plans/cld-010-brief.md`
- Accepted plan: `docs/plans/cld-010-file-sharing.md`
- Adversarial reviews: `docs/plans/cld-010-adversarial-review.md`, `docs/plans/cld-010-backend-adversarial-review.md`
- Simplicity reviews: `docs/plans/cld-010-simplicity-review.md`, `docs/plans/cld-010-backend-simplicity-review.md`
- Episode state: `docs/plans/episode-state.md`
- Cloud instructions: `AGENTS.md`, `ENGINEERING_STYLE.md`
- Foundry instructions: `C:/Users/ASUS/Desktop/projects/allies-foundry/.forest/worktrees/ft/fnd-011-file-sharing/AGENTS.md`, `C:/Users/ASUS/Desktop/projects/allies-foundry/.forest/worktrees/ft/fnd-011-file-sharing/ENGINEERING_STYLE.md`
- Worktrees: `C:/Users/ASUS/Desktop/projects/allies-cloud/.forest/worktrees/ft/cld-010-planning` and `C:/Users/ASUS/Desktop/projects/allies-foundry/.forest/worktrees/ft/fnd-011-file-sharing`
- Current implementation mode: terra_xhigh, with bounded Cloud and Foundry packets on separate repository files. Run Ponytail Full before editing. The parent owns integration and final verification.

## Task CLD-010/FND-011 — Coordinated private file delivery

### Objective

Implement the accepted Cloud and Foundry backend scope for private, immutable file delivery. Keep Interface work out of scope.

### Dependencies

- The accepted Cloud/Foundry contract in the plan.
- Cloud and Foundry target worktrees are clean and based on fetched `origin/dev`.
- The worker owns both repositories because the Cloud/Foundry protocol must remain coordinated. Use separate commits and future PRs for each repository.

### Owned Files Or Systems

- Cloud file models, migrations, services, API schemas/controllers, storage boundaries, authorization, queue preparation, publication/retry/retrieval/cleanup, and focused tests in the Cloud target worktree.
- Foundry runtime file staging, versioned contracts, publication tool, durable spool/recovery, workspace cleanup integration, sanitized public fixtures/docs, and focused tests in the Foundry target worktree.
- Required contract and test fixtures in both target worktrees.

### Required Context

- Implement only the accepted plan. Do not add Interface behavior, public sharing, a general file manager, unsupported media, or a general Ally deletion feature.
- Preserve Cloud tenant truth and Foundry runtime truth. Do not import Cloud Django models into Foundry.
- Keep Foundry public content portable and free of private paths, deployment data, Nabu snapshots, credentials, or customer data.
- Use the existing dependency/tooling conventions. Do not add a dependency or speculative framework without a concrete plan requirement.

### Acceptance Criteria

- Incoming files are private, owner- and Ally-scoped, prepared before ordered execution, and sent with optional text exactly once.
- Returned files publish a fixed version, preserve the working copy, and retry without new model execution or a regenerated source.
- Repeated, stale, cancelled, failed, and cross-scope operations have the planned safe outcomes.
- Cleanup and deletion integration preserve retained/recoverable data and remove only authorized profile data.
- Cloud and Foundry share a compatible, versioned `file_input_v1` contract with compatibility coverage.

### Validation

- Use focused Cloud and Foundry tests during implementation.
- Run the accepted root checks: Cloud `make check`, `make lint`, focused `make test APP=files/tests`, `make test APP=chat/tests`, `make test APP=allies/tests`, `make test APP=activities/tests`; Foundry `make check`, `make validate`, `make lint`, and focused `make test APP=<path>`.
- Run migration, OpenAPI, contract, PostgreSQL, image, and integrated checks that the plan requires when their environment is available. Report unavailable external/provisioned checks as skipped with the reason.

### Required Result

- Files changed in each repository
- Separate commits and test results for Cloud and Foundry
- Assumptions and blockers
- Contract compatibility and integration notes
- The parent may push feature branches and create PRs under the later user authorization. Workers do not push, deploy, mutate Nabu, or merge PRs.

## Resumption wave: inbound delivery

### Cloud packet
- Own Cloud backend files, chat preparation/dispatch, internal accepted-file access, and their tests.
- Complete Phase 3 ordered preparation and recovery, including retry/remove/cancel, durable draft recovery, history projections, and immutable manifest dispatch behind a separate disabled delivery capability gate. Preserve the admission production block.
- Supply the accepted scoped internal read endpoint using existing internal service authentication, exact message/binding/manifest membership, and bounded binary reads. No public object URLs.
- Preserve text and routine behavior. Freeze file manifests into the existing outbox only when all files are ready and the negotiated delivery gate is satisfied. Until Foundry proof exists the gate stays off.
- Tests must cover owner/Ally ancestry, readiness/order, cancel versus claim, duplicate/stale operations, successful-byte preservation, empty text, and unchanged text/bootstrap/routine contracts.

### Foundry packet
- Own Foundry backend file transport, runtime incoming staging, structured Hermes input, and associated portable tests/docs only.
- Implement Phase F2 incoming staging against the accepted Cloud endpoint. Use the existing backend service credential; runtime must never receive it. Require current attempt/profile/generation and manifest membership.
- Stage the complete manifest before model invocation; verify size/hash, bounded reads, safe paths, atomic commit and replay without overwriting edited working copies. Preserve renewal and existing profile cleanup fences.
- Implement files-only structured input through the pinned Hermes integration. Keep runtime capability disabled until integration proof. Preserve routine command behavior; routines do not inherit conversation file authority.
- No publication/spool/retry implementation in this wave. No edits to Cloud.

### Shared contract and validation
- Use the accepted plan routes and descriptor shape verbatim. Report ambiguity to the parent before a contract change.
- Current integrated bases: Cloud 875df52, Foundry 231da4c. Nabu spec revision is unchanged and verified through MCP.
- Use locked virtual environments; set DJANGO_DEBUG=true for Foundry local tests. Routines fixture bytes require LF; parent restored canonical LF working bytes without content changes.
- Commit coherent implementation increments with the Codex trailer. Do not alter the parent's planning/state files. Report exact commands, results, changed files, and release blockers.

### Independent inspection helpers
- Own only new files/inspection.py, files/previews.py, their focused test modules, and docs/operations/file-inspection.md.
- Implement bounded type validation, an isolated ClamAV transport adapter that fails closed, and inert preview helpers using existing dependencies.
- Keep intake, storage, models, settings, tasks, APIs, and dependency files with the Cloud inbound worker. Report required interfaces to the parent.
- Fake transport tests do not establish live scanner or decoder proof. Unavailable PDF/HEIC isolation remains a release constraint.

## Resumption wave: publication and retention

- Cloud worker owns publication reservation/status/retry, private retrieval, reply-link validation, inspection tasks, and bounded cleanup. Use the accepted API shapes and lock order. Preserve immutable versions, draft references, and accounting across uncertain I/O.
- Foundry worker owns durable PublicationIntent, immutable local spools, the model-facing publication tool, recovery after execution ends, bounded wake discovery, and profile cleanup. Recovery must use the original source and current profile generation without a model execution.
- Workers coordinate the exact internal transport directly. The full Cloud mount is `/api/v1/internal/v1`. Authentication uses the existing Bearer event-service token. No new credential header is required.
- Keep source edits separate from frozen versions. Status placeholder creation cannot downgrade an existing publication. Retry preserves successful file IDs and bytes.
- Parent owns integration, pinned-source image checks, separate reviews, and planning state. Workers commit coherent increments and report exact validation. No worker pushes, merges, deploys, or changes Nabu.
