# Routines staging follow-up

Fast route; user requested one PR per affected repository, all second-pass fixes together, mobile held. Visual review uses existing Figma nodes 370:6622, 372:6829 and 376:7026; no separate HTML plan.

Replace the trailing routine list with cards at their source message; legacy cards and results use chronological attribution. A source on an unloaded older page stays with that page and appears when Earlier messages loads it. Do not float it under unrelated current messages. Retain Cloud's structured action identities privately and send friendly text to the Ally.

Use compact accent cards, a routine timer icon, readable schedules, expandable Full prompt, and responsive details/delete dialogs centered inside the chat. Hide implementation revisions/generations. The latest user request restores UI deletion confirmation: Cancel sends nothing; Confirm sends the action to the Ally without another question. Lock dismissal while sending, restore focus on cancellation, and guard completion against a changed selected routine. Native dialog bounds follow the chat shell while the backdrop separates the whole page in light/dark mode.

Validation: full suite 869 tests/116 files passed; final affected frame/model suite 71 passed; typechecks and production build pass; lint 0 errors/36 existing warnings. Production browser tests pass on desktop and mobile-width web in light/dark mode, covering reload/placement, geometry, prompt disclosure, cancel/focus, in-flight dismissal lock, friendly text/private metadata and browser timezone. Reference screenshots reviewed. Independent simplicity/correctness review, with cancellation race fixed and pagination behavior explicitly retained.

Cloud schema pinned to 1cb456d929f6e3985875d204d3751315d7ba8e64. Deploy Cloud #42 before Interface and promote Foundry #56's image pair. Local Docker proof of routine creation/trigger/result passes, but a fresh real-model staging test remains after promotion. Rollback by reverting the web PR; no new dependency, service or environment variable. No merge/deployment performed.
