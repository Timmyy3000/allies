# Personal onboarding

Route: fast. Owner: Codex. User authorized implementation in PR #50.

## Scope and approach
Use existing Allies art, orange accents, layout, and controls. Introduce Allies, ask what the person needs help with, then name, appearance, personality, and the existing preview/authentication handoff. Returning signed-in users start at responsibility. Keep answers in the existing provider, and preserve the Cloud job and OAuth contracts. Short answers receive an optional, once-per-flow invitation to add context; they can continue without adding anything. Empty answers remain invalid.

Affected surfaces: public route/drawer, signed-in creation, onboarding store and components, browser journey tests. No separate HTML: the working preview is the visual review.

## Acceptance and validation
- Intro uses existing animated Allies and cursor motifs; reduced motion is respected.
- Responsibility precedes name, survives backwards navigation and becomes the existing job.
- Name has only its heading and input. Appearance and personality questions use the chosen name.
- Short-answer nudge is dismissible; no new minimum length.
- Existing 200-character Cloud limit stays visible; longer descriptions require a future shared contract change.
- Guest preview/Google return retains original responsibility, appearance, greeting and first reply without duplicate creation.
- Check mobile/light and desktop/dark layouts and signed-in entry.
- Run `bun run test:run --project web` for onboarding and creation tests; scoped ESLint, `bun run build:web`, and Playwright guest-handoff/landing against port 3000.
- Separate correctness and simplicity reviews before commit.

## Risks and rollback
Reordering can break back navigation, drawer entry, or resume; exercise these transitions. Preserve auth and creation machinery. Revert this onboarding commit to restore the prior order. No dependencies, backend changes, or migrations.

## Delivery evidence

- Production build and TypeScript pass on the final code; preview runs at localhost:3000.
- 38 focused onboarding, resume, preview, authenticated-creation and analytics unit tests pass.
- Four public onboarding browser tests pass, including mobile/light and desktop/dark simulated Google handoff. Both nudge paths accept the original answer, going back to edit the responsibility does not repeat the prompt, and the exact job reaches Cloud once.
- Six desktop/mobile Home smoke checks pass for signed-in creation entry, shape-selector layout, conversation reload, and public app entry. These ran before the final job-editor height-only adjustment; the affected guest screens were rechecked afterward.
- Scoped ESLint passes with nine pre-existing warnings in the landing component; diff whitespace check passes.
- Correctness review: entry points, reordered back map, resume compatibility, API bounds, preserved identity, and no duplicate creation checked. Extended the telemetry step union for intro; corrected browser selectors for the Ally-only list preview.
- Simplicity review: existing store, layout, artwork, selectors and handoff reused. One intro component and two small flow flags; no new libraries or service calls. No outstanding P0–P2 findings.
- Canonical product design note updated in Nabu with accepted direction, implementation status, and the open longer-description contract limitation.
- Existing PR retained at the user's request; onboarding is a separate focused commit so it can be reviewed or reverted independently from the already-reviewed beta polish.

## Owner refinement — 10 September

Supersedes the first visual take: minimalist copy, no supporting paragraphs, caption, avatar labels, or name-page responsibility card. Keep the job suggestion chips. The optional nudge is a single line under the editor, with Continue in the existing footer. Introduction reuses the existing random curved wandering animation with orange, blue and lavender Allies; keep paths within the scene and respect reduced motion. Appearance asks “How should [name] look?” and personality asks “What personality should [name] have?” Long names wrap safely.

Refinement validation: final production build and TypeScript pass; 33 focused unit tests pass; five browser checks pass (mobile/light and desktop/dark guest handoff, entry/back navigation, and full/reduced motion). Scoped ESLint has no warnings or errors. Live in-app-browser inspection confirmed the wandering introduction, inline nudge, empty name page, and name-specific appearance/personality headings. Correctness review checked scene resizing, animation cleanup, path bounds and back navigation; simplicity review removed unused cards/copy/styles and reused the existing wander component. No outstanding P0–P2 findings.

Owner correction: intro heading is exactly “Everyone needs a little help from allies”; name placeholder removed. Intro now receives the existing landing FollowAlly elements directly, preserving their 36px artwork, rounded cursor, proportions and red/blue/yellow colours. Custom intro SVG/CSS removed. Production build, scoped lint and all five onboarding browser checks pass; live browser inspection confirms the shared artwork and heading. Correctness/simplicity review found no issues; no landing artwork implementation was changed.
