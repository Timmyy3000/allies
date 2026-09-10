# Routines staging follow-up

Fast route. User authorized one PR per affected repository for all second-pass fixes; no merge/deployment and mobile remains held.

Persist optional structured routine action context separately from readable chat text. Validate owner, workspace, Ally, conversation and optional execution/approval identities. Include timezone/action context in replay comparison and preserve both on retry and dispatch. A confirmed modal deletion still runs through the Ally and the existing challenge/atomic revision checks; ordinary chat retains earlier-turn confirmation.

Retain an immutable nullable source-message reference on a routine so web can place creation at its original turn. Reuse the existing activity vocabulary and presentation path for nine routine operation kinds. No new scheduler, service or environment configuration.

Acceptance: foreign identities cause no message/outbox mutation; retries do not change intent; modal-confirmed deletion needs no second question; source association survives edits; typed results stay truthful. Companion Foundry handles the Hermes wrapper/schema fix; Interface handles rendering and controls.

Validation: full suite 759 passed/25 skipped; final chat/services and routine tool checks 39 passed/1 skipped, including added cross-scope rejection coverage. Django/migration, Ruff and format checks pass. Local Docker creation/replay, timezone claim, separate scheduled run and successful result projection passed. Independent simplicity and correctness review; required negative ownership-test finding addressed.

Deploy Cloud migrations before the companion Interface changes. Publish/promote companion Foundry images through the existing release workflow and verify a freshly loaded staging browser. Rollback code by reverting the PR; nullable additive fields may remain in the database. No live-model staging success is claimed by scripted local proof.
