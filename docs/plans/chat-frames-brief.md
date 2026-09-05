# Pixel-perfect web chat frames

## Kickoff status

- Type: feature
- Planning mode: full (substantial visual state set with interaction, accessibility, and responsive risks)
- Current phase: awaiting user approval
- Implementation delegation: always
- Delegation source: kickoff fallback because the user did not opt out
- Worktree manager: Forest
- Branch: `web/feat/chat-frames`
- Base: `web/dev/figma-chat-ui`
- Planning worker: `sol_planning_worker`
- Planning worker source: repository-local `.agent/kickoff.yaml`
- Review worker: `sol_review_worker`
- Review worker source: repository-local `.agent/kickoff.yaml`
- Implementation worker: `luna_execution_worker`
- Implementation worker source: repository-local `.agent/kickoff.yaml`
- Task workspace: `docs/plans`
- Created: 2026-09-03
- Target date: not specified

## Objective

Implement the supplied Allies chat handoff as a pixel-accurate web conversation experience. The web UI must cover every requested chat frame and state in the imported design evidence except the frame named `chat ~ keyboard state`, which is intentionally out of scope because this implementation is web rather than mobile.

The result should feel like one coherent conversation surface, not 25 unrelated mock screens. It should preserve the existing Allies product and Cloud boundaries, use the existing Open Runde typography and Ally artwork, and expose the states through the smallest maintainable state/fixture mechanism that does not fake a production backend contract.

## Design evidence

The source is the user-supplied Figma handoff imported through Aphrodite under the `handoff` alias. The target page is the `product` page. All listed frames are 375 × 812 reference frames and share the mobile-sized composition that must be adapted to a responsive web viewport.

Requested frame IDs:

- `315:1612` — `chat`
- `315:2050` — `chat ~ thinking state`
- `346:5812` — `thinking`
- `315:2837` — `chat ~ ally reply`
- `315:2927` — `chat ~ long message`
- `315:3009` — `chat ~ long message`
- `370:6544` — `routine`
- `370:6622` — `routine created`
- `346:5714` — `sleeping`
- `346:5880` — `waking`
- `315:3256` — `chat ~ error message`
- `347:5953` — `queueing`
- `362:6356` — `failed`
- `365:6452` — `failed b`
- `355:6222` — `approval request`
- `355:6112` — `multiple message queueing`
- `331:4419` — `chat ~ interrupted mid work`
- `332:4537` — `chat ~ cart`
- `332:5289` — `chat ~ image display`
- `332:5604` — `chat ~ cart`
- `332:4983` — `chat ~ cart expanded`
- `372:6829` — `chat ~ routine`
- `376:7026` — `chat ~ routine delete`
- `332:4740` — `chat ~ cart expanded`
- `315:3141` — `chat ~ activity dropdown`

Explicit exclusion: `315:1827` — `chat ~ keyboard state`.

Known design anchors include a 375 × 812 white frame, 20 px horizontal margins, 40 px header controls at y=68, a 335 × 48 px pill composer at y=706, Open Runde, `#121212` body text, `#A0A0A0` muted text, `#F3F3F3` surfaces, `#FD304F`/`#FF2D55` Ally accents, and a 36 px Ally identity artwork. The planner must verify these anchors and all state-specific geometry from Aphrodite rather than relying on this abbreviated summary.

## Product and architecture constraints

- The Interface talks only to Allies Cloud; it must not call Hermes, Foundry, Fly, or other runtime services directly.
- Keep the existing conversation query, activity projection/stream, queued-message persistence, retry behavior, and Ally appearance resolution as the source of truth where they already cover the requirement.
- Use product language for lifecycle and activity states. Do not expose raw runtime terms in user-facing UI.
- Preserve the user’s message on send failure and provide an accessible retry path.
- Keep the web implementation in `apps/web`; do not modify the mobile client for the excluded keyboard state.
- Prefer semantic HTML, keyboard-operable controls, visible focus, sensible labels, and reduced-motion behavior.
- Reuse existing project assets and patterns before adding dependencies or abstractions.
- Do not add a new backend contract unless repository evidence proves an existing contract is insufficient; if a visual-only state switch is required for QA, keep it explicitly fixture-driven and separate from production data ownership.

## Evidence inspected

- `AGENTS.md` and `ENGINEERING_STYLE.md` — workflow, boundaries, planning, and validation rules.
- `apps/web/AGENTS.md` — Next.js 16 guidance requirement for framework changes.
- `docs/templates/PLAN_TEMPLATE.md` — required Markdown plan structure and hygiene.
- `apps/web/app/home/home-workspace.tsx` — current roster/conversation data path, Cloud activity handling, retries, and state ownership.
- `apps/web/app/home/home.module.css` — current conversation layout and responsive styling.
- `apps/web/components/ally-avatar.tsx` — existing Ally artwork, motion, and reduced-motion behavior.
- `projects/allies/product/allies-product-design-spec.md` — M2 conversation requirements and lifecycle language.
- `projects/allies/engineering/specs/conversation-and-streaming.md` — Cloud conversation/activity boundary and event vocabulary.
- `projects/allies/engineering/guides/interface-development.md` — web structure, accessibility, responsiveness, and baseline checks.
- Aphrodite `handoff` screen inventory and bounded design contexts for the 25 in-scope frames.

## Acceptance direction

The final plan must make these measurable:

1. Every in-scope frame has a deterministic web representation with the correct content, ordering, state affordances, colors, typography, surfaces, spacing, and Ally artwork; the excluded keyboard frame is not implemented as a target state.
2. The conversation remains usable at desktop and narrow web widths, with the 375 px reference composition preserved as the fidelity baseline.
3. Real Cloud-backed conversation behavior continues to work for loading, empty, streaming, queued, waiting, retrying, failed, and completed states; visual-only states never bypass the Cloud boundary.
4. Cart, image, routine, approval, activity, and deletion surfaces have clear ownership, safe dismissal/confirmation behavior, and accessible controls.
5. Focus order, labels, contrast, reduced motion, and responsive overflow are covered by focused automated or manual checks.
6. The implementation adds no unnecessary dependency or broad abstraction and passes the repository’s relevant lint, typecheck, test, build, and visual/browser checks.

## Open decisions for planning

- Whether the existing `HomeWorkspace` should be incrementally refined or whether a small page-owned chat state model should be extracted from it.
- How the 375 px Figma states should map to the existing desktop roster + thread layout without changing the product’s established navigation.
- Which commerce/routine/image/approval surfaces can be represented with existing data types and which require a clearly bounded visual fixture for review.
- The minimal browser verification route and viewport matrix needed to compare the implementation against the Figma reference frames.
- Any Aphrodite asset extraction gaps that require a tracked local copy or a CSS/native equivalent.

## Handoff to planning

The planner must inspect the branch repository and all cited evidence, use the local plan template, create the complete Markdown plan under `docs/plans/`, and create the required Lavish HTML artifact under `.lavish/`. It must not implement code or spawn additional workers. The plan must include the data path, state/caching ownership, all loading/error/retry/empty/permission behavior, responsive/accessibility checks, visual acceptance mapping for all 25 in-scope frames, risks, rollback, and concrete validation commands.

## Adversarial review disposition

The independent review on 2026-09-03 returned `Needs revision`. All findings are accepted for the planner to address before simplicity review:

- Activity presentation must be grouped by `messageId` and `conversationTurnOrdinal`, placed after the triggering user turn, and covered for multiple turns, replay ordering, conversation changes, and cap eviction.
- Production rendering must accept only production models; rich synthetic branches/actions must remain in a debug-only module with static import-boundary tests.
- The plan must pin the design revision/checksum, preserve a complete 25-frame measurement/content/asset manifest, identify a baseline approver, and retain durable sign-off links.
- Visual regression validation must be a stable executable CI/pre-merge gate with pinned browser/runtime versions and retained diff artifacts.
- Production must define and test 401, 403, and inaccessible/not-found behavior for load, send, retry, and activity requests without stale cross-scope data or ineffective retry actions.
- Preview/staging exposure of `/chat-frames` is an owner decision; the default revised plan must choose a safe guard when no decision is available.
- Responsive, zoom, WebKit, and Safari validation must name executable projects and measurable reflow, clipping, focus, and composer-overlap assertions.

Review record: `docs/plans/chat-frames.adversarial.md`.

## Second adversarial review disposition

The fresh independent review also returned `Needs revision`. Its five findings are accepted and must be routed through planning:

- Separate provisional baseline generation from the post-approval sign-off verifier so the initial capture path is not circular.
- Name the implementation PR target branch and ensure the required visual job is triggered and protected on that branch.
- Make production/debug boundary proof cover aliases, re-exports, dynamic imports, and CommonJS, or add an equivalent production bundle-graph assertion.
- Replace symbolic-only asset evidence with complete per-frame mappings to tracked assets, verified reusable assets, masked OS chrome, or documented native/CSS substitutions, resolving the compacted Aphrodite asset diagnostics.
- Make missing visual artifacts fail the CI upload step with an explicit expected-file validation and `if-no-files-found: error`.

The full second review is appended to `docs/plans/chat-frames.adversarial.md`; no application code changed.

## Simplicity review disposition

The independent simplicity review returned `Needs revision`. Its findings and disposition are appended to `docs/plans/chat-frames.adversarial.md`. The plan now makes the CI URL post-run evidence rather than a sign-off prerequisite, keeps Playwright-managed failure diagnostics in the suite's single results artifact, uses the machine-readable manifest as the sole asset ledger, and keeps full raster/layout coverage in Chromium with representative Firefox/WebKit behavior checks. No application code changed.

## Final gate status

The final bounded adversarial verification returned `Pass` after the simplicity revisions. The plan and Lavish HTML now have matching SHA-256/byte metadata and no duplicate HTML IDs. Implementation is still paused at the user-approval gate; no application code has changed.
