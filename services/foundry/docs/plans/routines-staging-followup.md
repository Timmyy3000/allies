# Routines staging follow-up

Fast route; user authorized all fixes in one PR per repository. No merge or deployment.

The 12:42 staging test produced an accepted `allies_routine_result` through Hermes's `tool_call` wrapper, but the runtime recognized only direct calls and reported failure. Plugin schema registration also hid the required arguments from discovery.

Fix the existing parser and plugin registrations, retain result identity/order/status/payload checks, and send bounded routine activity names through the existing activity stream. Align the system instruction with Cloud's authenticated modal-confirmation context; Cloud still owns deletion authorization and scheduling.

Acceptance: direct and wrapped results succeed; malformed, duplicate, rejected, or out-of-order reports fail; discovery exposes required fields; activities expose no arguments. The existing cron tool remains disabled.

Validation: backend suite 646 passed/13 skipped; Linux runtime suite 651 passed/2 skipped, 90.02% coverage; Hermes image builds and schema/activity smokes pass. Local Docker proof created and replayed a routine through Hermes/Foundry/Cloud, preserved Europe/Berlin, admitted and claimed a separate scheduled conversation, and delivered a successful typed result to the original chat. Scripted tool execution, not a live-model staging test. Separate Sol simplicity/correctness review found no actionable issues.

Rollout: merge companion Cloud support before Interface. Publish and promote the updated Hermes/runtime images together through the existing release workflow, then verify the test Ally uses them. Roll back by reverting this PR and promoting the prior image pair. No new service or environment variable.
