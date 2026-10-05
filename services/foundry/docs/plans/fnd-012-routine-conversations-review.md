# FND-012 plan review record

Clean plan: [fnd-012-routine-conversations.md](fnd-012-routine-conversations.md).

The planning author performed separate correctness and simplicity checks, then the required better-docs and humanizer passes. No independent reviewer or additional agent was invoked. This record is not the independent implementation approval recorded in the episode.

## Design corrections before editorial review

- Replaced an overbroad claim about global conversation-reference exclusion with workspace-scoped resolution and explicit recognition that a workspace lock cannot exclude another workspace.
- Made the routine profile foreign key and its equality with the execution profile explicit, because the proposed partial unique constraint needs a concrete column.
- Specified one immutable prompt copy and transactional mapping between routine lifecycle and existing execution/attempt status.
- Added the PostgreSQL CI job, conditional power-accounting seam and final feasibility evidence path to the file map.

## Editorial comparison

The following line comparison records the prose edit; the complete clean file is linked above. No contract, acceptance criterion, limit, command or evidence claim was changed by the editorial passes.

```diff
-All relation invariants must be checked under locks: run execution/profile/workspace agree; owner/Ally/binding scope agrees with dispatch; main binding is that profile's existing main chat; run, main and execution IDs are pairwise different.
+Check all relation invariants under locks: run execution/profile/workspace agree; owner/Ally/binding scope agrees with dispatch; main binding is that profile's existing main chat; run, main and execution IDs are pairwise different.
```

Better-docs checks: retained template structure, ownership, explicit constraints, uncertainty and source evidence; kept the active verb change local. Humanizer checks: retained technical terminology and all numbers/code/link targets; no further prose changes were needed.

## Validation basis

Read preparation, repository policy, released contract/fixture/lock, runtime/backend seams, canonical routines specification/ticket and the supplied CLD-012 feasibility note. Hashes matched the released tuple before and after planning. Production files have no tracked diff. Existing untracked normative artifacts and episode state were preserved. Implementation tests were not run for this documentation change; exact future commands and prior baseline evidence are distinguished in the plan.

Plan assumptions: preserve the main binding, scope routine leases by routine identity, reserve an attempt for the accepted receipt, and retain durable approval continuation while releasing the worker slot. Release still requires Class B, PostgreSQL races and CLD-013 integration. Only the exact wire gaps documented in the clean plan require cross-team clarification.
