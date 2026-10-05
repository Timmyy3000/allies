# Attachment motion prototype

Fast route, local design review only. Timi requested a phone-accessible interactive prototype in the actual chat and composer, using the existing Allies design language. Backend integration remains in the other task.

Use the production ConversationFrame and ConversationComposer with optional attachment presentation slots. A development-only route owns sample history, local selections, preview sending, and the expanding Camera / Photos / Files surface. Nothing uploads and no live conversation is modified. Existing callers remain unchanged.

Reuse Open Runde, existing colors, avatar, chat layout, and motion dependency. Animate the persistent surface between menu and selector; animate captured or selected images into composer thumbnails. Support multiple selection, removal, dismissal, device picking, reduced motion, and camera unavailability. Enforce 10 files, 25 MB each and 50 MB total. Samples are labeled.

Acceptance: phone viewport has no horizontal overflow; menu expands without detached popups; selected items settle into composer; typing and local preview sending work in the real frame; camera tracks stop on close; text-only composer tests still pass.

Validation: focused existing composer tests, web TypeScript, lint on changed files, browser interaction and phone-size layout checks. Serve the isolated app on a separate LAN port. No Cloud/Foundry edits. Remove the development route and optional hooks to roll back. No production release or accepted design decision is implied by this prototype.
