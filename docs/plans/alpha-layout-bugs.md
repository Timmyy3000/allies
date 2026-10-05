# Alpha layout bugs

Fast route: fix the four layout reports read in Discord #alpha-test on 2026-09-07. The Google icon report is already addressed by 23ccff5.

Use existing components and CSS: reserve footer space and scroll the completed mobile introduction; lower the roster CTA while preserving safe-area padding; center the avatar carousel in its available space, with a minimum height on short screens; keep mobile composer text at 16px to avoid iOS focus zoom. No auth, transport, state ownership, or backend changes. No new dependencies.

Acceptance: introduction CTA and legal links cannot overlap at short mobile heights; roster CTA remains visible near the bottom; tall-screen carousel uses the available vertical space; focused composer and text remain within viewport bounds. Preserve access to content on short screens and browser pinch zoom.

Validation: extend existing Playwright home-smoke and chat-frame behavior tests; run against the existing local server with HOME_SMOKE_PORT=3000 and CHAT_FRAMES_PORT=3000, CHAT_FRAME_RASTER=false; run lint:web and web typecheck. No screenshot rebaseline. Real iOS keyboard behavior still needs device confirmation because desktop WebKit does not reproduce the OS keyboard.

Risk: geometry changes at unusually short heights. Rollback: revert this focused layout commit. No unresolved product decisions or HTML review needed.

Verified: 10 home-smoke tests and 15 chat-frame behavior tests passed; web typecheck passed. Web lint passed with 34 existing warnings when generated Playwright reports and test artifacts were excluded. Correctness review checked safe-area spacing, short-screen scrolling and unchanged single-line composer height; simplicity review retained CSS changes and the existing components without extra state or dependencies. Actual iPhone keyboard confirmation remains a tester follow-up.
