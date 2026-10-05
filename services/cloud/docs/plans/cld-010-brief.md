# CLD-010 work brief

## Scope
Current resumption: Complete backend implementation and open separate PRs into dev under the linked task's later authorization. Use terra_xhigh for implementation and fresh sol_high review sessions. Nabu saved-profile reload and authenticated tree verification passed on 2026-09-09; the approved specification is unchanged. Integrate current dev before further implementation. No merge, deployment, Interface work, or Nabu mutation is authorized.

Execute the accepted CLD-010/FND-011 implementation plan across Cloud file storage/delivery and Foundry receipt/publication. The user authorized a Terra high worker for both backend repositories on 2026-09-09. Interface implementation remains later. Do not publish a contract to Nabu.

## Authority
The approved Nabu specification is `projects/allies/engineering/specs/cld-010-user-message-file-attachments.md`. Source snapshots and revisions are in `cld-010-sources.md`. Nabu remains canonical. Inspect the current repository and identify mismatches rather than treating old plans as current truth.

## Required outcomes
- Private uploads and immutable returned file versions, with owner and Ally scope.
- Limits in both directions: 25 MB per file, 10 files per message, 50 MB total.
- Optional text and all accepted files reach the Ally together, once and in order.
- Failed preparation blocks later messages to that Ally. Other Allies can continue.
- Retry retains successful uploads. Removal requires an explicit send retry. Cancellation before delivery prevents later delivery and supports draft restoration.
- Stable private metadata, preview and download access for old versions. Working-file edits do not change shared versions.
- No expiry while the Ally exists. Integrate Ally deletion and bounded temporary-upload cleanup without breaking recovery.
- Resolve engineering choices for extensions, storage, safe previews, malware inspection, cleanup, and aggregate storage controls.
- Publish a concrete Cloud/Foundry and Interface contract before dependent implementation. Final acceptance needs integrated evidence from FND-011 and INT-106; these are not circular start dependencies.
- Include concrete Foundry changes: incoming file staging before model execution, safe Ally runtime file-publication capability, fixed-version spool, persistent retry recovery, working-file continuity, and deletion integration. A raw machine path is not a usable product link.
- Define Cloud/Foundry backend integration proof now and preserve the later Interface/device acceptance gate. Do not label backend-only proof as complete user-facing feature acceptance.

## Planning and review
Use Astra low for planning and separate independent adversarial and simplicity reviews. Terra high is saved for later implementation. Use the full repository plan template and complete matching Markdown/HTML, as required by the user-supplied instructions. Use Allies identity and the prescribed visual foundation. Apply ADS-STE100 writing guidance. Read README, Makefile, CI and tests to name exact validation commands. Identify small coherent PR slices without omitting contract or integration proof.

Keep one combined master plan in the existing Cloud planning worktree. Foundry is public: keep private Nabu snapshots and coordination details in Cloud; specify only portable, sanitized contracts/docs for future Foundry commits. Preserve Foundry provider-neutral core boundaries and existing runtime/workspace ownership.

## Artifacts
- Worktree: `C:/Users/ASUS/Desktop/projects/allies-cloud/.forest/worktrees/ft/cld-010-planning`.
- Base: `origin/dev` at `dd8bba6` when created.
- State: `docs/plans/episode-state.md`.
- Plan: `docs/plans/cld-010-file-sharing.md` and matching `.html`.
- Sources: `docs/plans/cld-010-sources.md`.

## Acceptance of planning
The plan covers the approved specification, has concrete failure and concurrency contracts, cites repository evidence, resolves or clearly identifies engineering decisions, names exact validation, and passes both independent reviews. The user accepted the plan on 2026-09-09 and authorized Cloud and Foundry implementation after remote synchronization. Interface implementation remains later.

## Foundation-slice record

- Cloud Phase 1 commits: `7e19499`, `1c1866d`, `2d467d1`, `e8566f8`, and `620292a` add the private file-domain and disabled `file_input_v1` contract foundation, then resolve all review findings.
- Foundry F1 commits: `816ce01`, `12a9128`, and `ef4c25b` preserve the compatible optional manifest, enforce the same bounds, and pin matching file-bearing fingerprints.
- Independent Ponytail reviews identified six reductions. All are applied. Independent correctness reviews identified CR-001 through CR-004. All are resolved.
- Direct locked-environment checks passed: Cloud system check, migration drift, and 27 focused tests; Foundry system check and 47 runtime contract tests. The shared golden fixture SHA-256 is `A2D91FB63E3CD5FDC15602107FBF98E4F266257AD567BA697FED9F5EB2C2C903`. `uv` is unavailable on PATH, so Make wrappers remain unrun.
- The next slice starts private Cloud intake/storage and Foundry incoming staging. It must add the planned readiness and ancestry gate before Cloud dispatch includes a file descriptor.

## Rejected Phase 2A admission attempt

- Cloud commits `165a80a` and `1c9815e` introduced a partial reservation/upload API. Independent correctness review found six P1/P2 gaps: unbounded request buffering, no production storage configuration, missing chat and storage admission controls, no receiver lease or recovery, ready promotion without inspection, and Interface-contract drift.
- Cloud commit `54099c3` non-destructively reverts the partial API. The Cloud backend is identical to the accepted foundation before the attempt. Direct system/migration checks and 27 focused tests pass.
- The next admission slice must deliver the accepted controls as one reviewable contract. Do not expose a partial upload endpoint or dispatch a file descriptor before that point.

## Reviewed gated Cloud admission

- Cloud commits `cc1c2cc`, `6de4187`, and `cfba20d` replace the rejected partial API with a complete, gated intake boundary. Reservation is atomic with workspace byte accounting and existing queue and rate controls. Raw bytes stream in 64 KiB blocks with exact content length, a 25 MB file limit, a fenced receiver, and private object metadata.
- The API returns the accepted 202 reservation and validation responses. Foreign or missing ancestry remains an opaque 404. Storage faults return 503. A successful transport remains `validating`; only an internal, verified inspection and immutable promotion path can make a file ready. The endpoint neither dispatches a file nor calls Foundry.
- Production startup rejects enabled admission. The feature stays disabled until the team supplies the inspection worker, serving-boundary slow-body and receiver limits, an approved capacity, and the deletion-owner integration. No bucket, scanner, deployment, push, PR, or Nabu mutation was made.
- Independent simplicity review findings were applied. The first correctness review found seven P1/P2 issues; all were fixed. A second independent correctness review found no actionable P0, P1, or P2 finding. Direct final checks passed: system and migration-drift checks, Ruff, `git diff --check`, and 108 focused tests. The worker full suite result was 678 passed and 23 skipped. PostgreSQL-specific tests are skipped without a configured connection. The inherited local SQLite history still has the two pre-squash, unshipped migration names and was not altered; fresh CI/PostgreSQL migration apply remains required.
