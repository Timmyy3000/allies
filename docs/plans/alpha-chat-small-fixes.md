# Alpha chat small fixes

Fast route: implement the contained, still-open web fixes from AT-019, AT-021, AT-007, and AT-009 on top of PR #29. Keep AT-004, AT-022, AT-023, and AT-026 out of scope because they require device evidence, state-semantics investigation, or an accepted design dimension. No API, persistence, or backend contracts change.

Approach: constrain queued previews while retaining their full accessible content and controls; make the responsive mobile composer use the explicit send button while desktop Enter-to-send and IME composition remain unchanged; keep the persistent Ally actor inside its reserved thread/header slots and hide stale overlay coordinates before a greeting/reply placement change can paint; derive a black-or-white bubble foreground from the supported Ally accent with WCAG relative luminance.

Affected surfaces: `conversation-frame-primitives.tsx`, `conversation-presence.tsx`, `conversation-frame.module.css`, and focused conversation tests. The existing mobile-home breakpoint remains the source of truth for responsive keyboard behavior. No new dependency or abstraction is introduced.

Acceptance: long unbroken queued text cannot widen the queue or hide its action; mobile Enter inserts a newline and only the explicit control submits, while desktop Enter submits, Shift+Enter inserts a newline, and composition never submits; greeting/layout updates do not animate the Ally through message content; user-bubble text reaches at least 4.5:1 contrast for every supported Ally color in both themes.

Validation: run focused Vitest coverage, `bun run lint:web`, `bun --filter web typecheck`, and `bun run build:web`; exercise the chat-frame preview at mobile and desktop widths when the local browser harness is available. Real iOS/Android software-keyboard behavior remains a tester retest.

Risks: breakpoint changes while typing could change Enter behavior, and arbitrary legacy accent strings may not parse. Use the live responsive hook, preserve IME checks, and fall back to white for invalid colors. Rollback is reverting this focused commit. No HTML plan review is needed.
