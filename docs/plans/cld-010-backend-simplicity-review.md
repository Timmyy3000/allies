# Simplicity Review

## Verdict

Lean.

This fresh independent review covers the combined Cloud and Foundry plan after BADV-001 through BADV-003 were resolved. No required simplification remains. The review does not authorize implementation. Interface implementation and device acceptance remain later work.

## Findings

| ID | Classification | Plan area | What to cut | Replacement | Preserved outcome |
| --- | --- | --- | --- | --- | --- |
| BSIM-001 | Keep | Publication recovery | None. A local journal alone cannot cause a sleeping workspace to wake before Cloud registration. | Keep the narrow PublicationIntent, existing wake path and bounded runtime recovery pass. | A frozen version remains discoverable after the source attempt ends, without another model turn. |
| BSIM-002 | Keep | Storage accounting | None. Cloud quota cannot bound local bytes copied before Cloud accepts them. | Keep local admission reservations and use existing profile cleanup. Do not add a general storage scheduler. | Failed publication cannot consume the shared volume without a bound; committed retry bytes remain protected. |
| BSIM-003 | Keep | Runtime integration | None. The plan already extends composition, profile reconciliation, cleanup and execution contracts. | Keep the two file modules at their separate runtime and backend trust boundaries. | Model tools receive scoped files without Cloud credentials or a second workspace lifecycle. |

## Complexity Delta

- Plan steps/phases: 7 -> 7.
- New layers/abstractions: unchanged; no general framework is proposed. An exact count is unknown because image bridge implementation details remain to be specified.
- New dependencies/services: unchanged. Reuse boto3 and the current runtime lifecycle. Inspection and preview isolation serve explicit safety requirements.
- New configuration/variants: unchanged. Keep admission and capacity controls; preserve the existing text path through omitted optional file fields.
- Touched surfaces: unchanged across Cloud and Foundry. Interface work remains outside implementation scope.
- Removed or avoided: no new retry-job table, reference-count table, public stream event, provider lifecycle, general file manager, or deletion UI.

## Protected Complexity

- Keep the durable intent, immutable local snapshot and Cloud publication as separate records. They hold different facts: recovery authority, exact retry bytes and product state. Combining them would leave an outage or restart gap.
- Keep the create-only failed placeholder and shared publication identity lock. The user needs a recoverable failure before full reservation; delayed status calls must not replace newer publication state.
- Keep local and Cloud capacity checks. They protect different storage systems, and rejected Cloud reservations can still leave valid local retry bytes.
- Keep separate runtime and Hermes permissions plus safe file opens. A path check alone does not prevent a model-side process from changing a spool or accessing another profile.
- Keep relation-based file protection and generation fences. Queued reuse, draft discard and cleanup can run concurrently; deleting either control can lose accepted bytes.

## Plan Feedback

None required. The delete, reuse and compress passes found no cheaper option that preserves the accepted recovery, isolation, version and quota outcomes.

Keep implementation within the named modules and existing lifecycle paths. Do not turn the file-specific intent or volume ledger into reusable job or storage frameworks. This is a scope guard, not a new plan requirement.

The plan now supplies local capacity defaults. Their operational acceptance remains a release decision, as stated in the plan. Backend proof does not replace later Interface and device proof.

## Review Metrics

- Started at: 2026-09-09.
- Completed at: 2026-09-09.
- Components challenged: intent and status projection; local snapshot and ledger; recovery polling and wake discovery; service boundaries; Hermes image tool and isolation; draft references; phased PR scope and validation.
- Simplify/remove findings: 0.
- Net machinery removed: 0; existing exclusions remain appropriate.
- Independent worker: yes, fresh Astra low session.
- Evidence: simplicity-review skill, ENGINEERING_STYLE.md, episode-state.md, cld-010-brief.md, complete cld-010-file-sharing.md, final cld-010-backend-adversarial-review.md, Foundry composition.py and focused profile lifecycle symbol evidence.
- Limits: used the supplied canonical source references and reviewed dispositions; did not refresh Nabu. No product tests ran. Only this report was written.
