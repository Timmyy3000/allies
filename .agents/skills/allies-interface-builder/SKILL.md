---
name: allies-interface-builder
description: >-
  Builds Allies web UI from a Figma plugin JSON payload (description + screens
  with screenId, imageUrl, htmlUrl). Analyzes the flow, writes a task log under
  apps/web, converts HTML to React with html-to-react-exact, organizes feature
  screens, Zustand stores, shared components, Playwright E2E tests, then creates
  a web/ platform branch. Use when the user pastes that JSON, asks to build
  Allies screens/onboarding/flows from Figma HTML, or invokes
  $allies-interface-builder / Allies Interface Builder.
---

# Allies Interface Builder

Build Allies **web** features from a Figma plugin JSON payload. Do not start
coding until the task is named, logged, and the copy/flow are clear.

This skill does **not** replace `$html-to-react-exact`. That skill converts
HTML into exact React. This skill owns analysis, structure, state, tests, and
branching.

## Before anything else

1. Confirm the payload matches [references/payload.md](references/payload.md).
2. Load `$html-to-react-exact` before converting any HTML. Search for
   `html-to-react-exact/SKILL.md` if it is not already in the skill list.
3. Read `ENGINEERING_STYLE.md` before naming a branch or writing commits.
4. Work **only** in the web package: `apps/web`. Do not put this feature in
   `apps/mobile`.

Do **not** use Fan IQ fonts, Fan IQ UI primitives, or agentic-tester.
Allies web uses **Open Runde** (`apps/web/app/layout.tsx` / `app/fonts`).
E2E tests use **Playwright Test** directly.

Copy this checklist and keep it updated:

```
Allies Interface Builder:
- [ ] 1. Parse JSON and name the task
- [ ] 2. Create apps/web/<task>/TASK.md
- [ ] 3. Validate copy and flow
- [ ] 4. Plan feature structure
- [ ] 5. Identify reusable components
- [ ] 6. Convert HTML with $html-to-react-exact
- [ ] 7. Organize screens + Zustand
- [ ] 8. Playwright E2E for the full flow
- [ ] 9. Final verification
- [ ] 10. Create web/ branch from ENGINEERING_STYLE.md
```

## Input

The system receives JSON in this shape:

```json
{
  "description": "Human flow narrative: which screenId, which control, what happens next.",
  "screens": [
    {
      "screenId": "sign-in-page",
      "imageUrl": "https://…/sign-in-page.png",
      "htmlUrl": "https://…/sign-in-page.html"
    }
  ]
}
```

Rules:

- `description` is the **flow authority** for actions, validation, and
  destinations.
- Each `screens[]` entry needs `screenId`, `imageUrl`, and `htmlUrl`.
- Duplicate `screenId`s mean the same screen in more than one state — inventory
  once; keep each distinct state as a documented variant, not a duplicate
  route unless the flow requires it.
- `htmlUrl` is the visual/copy blueprint. `imageUrl` is QA only.
- Save the raw JSON verbatim to `apps/web/<task>/payload.json`.

A full example payload is in [references/payload.md](references/payload.md).

## Required execution order

For every incoming task, follow this sequence:

1. **Parse the JSON.**
2. **Understand the overall goal.**
3. **Choose a meaningful task name.**
4. **Create the task log inside `web`.**
5. **Document the goal, screens, copy, flow, state requirements, and implementation plan.**
6. **Validate all screen copy against the JSON.**
7. **Plan the component structure.**
8. **Identify shared/reusable components.**
9. **Use the HTML to React Parser skill.**
10. **Convert and organize the generated TSX into the correct feature structure.**
11. **Implement shared state using Zustand.**
12. **Extract reusable UI into the general/shared `web` components directory.**
13. **Write Playwright E2E tests for the complete flow.**
14. **Run and fix the E2E tests until the flow passes.**
15. **Perform final verification against the original JSON and task log.**
16. **Read `ENGINEERING_STYLE.md` and create the appropriate Git branch.**

The core principle is:

**Understand → Document → Plan → Convert → Structure → Implement → Test → Verify → Branch.**

Do not skip ahead to conversion or branching.

---

### 1. Analyze the JSON and Identify the Task

Before writing any code, analyze the JSON and determine the overall goal of the task.

For example, if the JSON contains a collection of screens representing an onboarding flow, the task should be identified and named something meaningful, such as:

`onboarding`

Task names should always be concise, descriptive, and based on what is actually being built.

Do not blindly derive the task name from individual screen names. Understand the overall purpose of the screens first.

Use kebab-case: `onboarding`, `sign-in`, `ally-setup`.

---

### 2. Create a Task Log

For every task, create a corresponding task folder **inside the `web` folder only**.

That folder is `apps/web/<task>/`.

This exists primarily for task memory and logging purposes.

The task folder should contain a Markdown file documenting:

* The name of the task.
* The overall goal of the task.
* What the JSON appears to be asking us to build.
* The screens involved.
* The exact copy/content required for each screen.
* The expected user flow.
* A proposed implementation plan.
* How the screens will be organized into components.
* Any reusable components identified during analysis.
* Any state that needs to be persisted or shared between screens.
* The E2E scenarios that need to be tested.

This document should act as the source of truth for the task before implementation begins.

Write it as `apps/web/<task>/TASK.md` using [references/task-log.md](references/task-log.md).
Also save `payload.json` in that folder.

Download each `htmlUrl` and `imageUrl` into the feature before conversion:

```text
apps/web/<task>/_html/<screenId>.html
apps/web/<task>/_images/screens/<screenId>.png
```

---

### 3. Validate the Copy Before Building

Extract and review the copy for every screen from the provided JSON.

Copy lives in the HTML behind each `htmlUrl`, plus any labels named in
`description`. Before implementation starts, make sure:

* Every screen has the correct copy.
* Headings, descriptions, labels, buttons, placeholders, and other text match the source.
* The order of the screens is understood.
* The transitions between screens are understood.
* No content from the JSON has accidentally been omitted.

The implementation should not begin until the intended flow and copy are clear.

Record the copy table in `TASK.md`. Mark unreadable strings `[unreadable]` —
do not invent replacements.

---

### 4. Plan the Feature Structure

Before converting or writing components, determine how the feature should fit into the existing project structure.

For example, an onboarding feature should follow a structure similar to:

```text
apps/web/
  onboarding/
    TASK.md
    payload.json
    components/
      index.tsx
      ...
    store/
      ...
    tests/
      ...
    _images/
      ...
    _html/
      ...
  components/          # shared / reusable across features
  app/                 # thin Next.js routes only
```

The existing project structure should be respected wherever possible.

Add a thin App Router page under `apps/web/app/` that renders the feature
entry (`components/index.tsx`). Do not dump the whole flow into `app/`.

#### Components

The feature-level `components` folder should contain components representing the actual screens within that flow.

For example:

```text
components/
  index.tsx
  welcome.tsx
  profile-setup.tsx
  confirmation.tsx
```

`index.tsx` should act as the entry point for the feature where appropriate.

Do not fill the feature-level `components` directory with arbitrary helper components.

If something represents a screen in the flow, it belongs here.

If something is genuinely reusable across multiple screens or features, it should be promoted to the **general/shared `components` folder under `web`** instead (`apps/web/components/`).

---

### 5. Reusable Components

While analyzing and implementing the screens, actively look for repeated UI patterns.

If the same component or UI pattern appears repeatedly across screenshots, generated HTML, or multiple screens, do not duplicate it.

Create a reusable component and place it in the general/shared components directory under `web`.

Feature-specific screen components should remain inside the feature's own `components` directory.

The goal is to avoid unnecessary duplication while also avoiding premature abstraction.

---

### 6. State Management

Use **Zustand** for shared/global state.

This is the default state-management solution for this project.

Do not introduce another global state-management library.

If `zustand` is not in `apps/web/package.json`, add it before creating stores.

Small pieces of state that are completely local to a single component can use React state where appropriate.

However, if state:

* needs to be accessed by multiple screens,
* needs to survive transitions within the flow,
* affects multiple components, or
* logically belongs to the overall feature,

prefer **Zustand**.

Think **Zustand first** for feature-level/shared state and React state for small, isolated component state.

Zustand stores should live inside the feature's `store` directory.

For example:

```text
onboarding/
  store/
    onboarding-store.ts
```

A feature may contain more than one store file if there is a legitimate architectural reason for separating them. Do not artificially force everything into one file.

---

### 7. Images and Assets

Do not place `_images` inside the `components` directory.

For example, this is incorrect:

```text
(onboarding)/
  _components/
    _images/
```

Instead, `_images` should exist at the feature level:

```text
(onboarding)/
  _images/
  _components/
  _store/
  _tests/
```

Keep assets separate from the screen components.

Extract HTML-embedded images with `$html-to-react-exact` into
`apps/web/<task>/_images/` (not under `components/`).

---

### 8. Convert the HTML to React

When implementation begins, use the **HTML to React Parser** skill (`$html-to-react-exact`).

Use the skill to convert the supplied HTML into proper React/TSX components.

Do not simply dump the converted output into the repository.

Never use `dangerouslySetInnerHTML` or an iframe of the design HTML.

After conversion:

1. Review the generated TSX.
2. Clean up the implementation where necessary.
3. Identify the individual screens.
4. Move each screen into the appropriate feature-level component.
5. Extract reusable UI into shared components where appropriate.
6. Connect the screens to the required Zustand store(s).
7. Ensure the copy still matches the source JSON.
8. Ensure the resulting implementation follows the project's existing conventions.

The parser is a conversion tool, not an excuse to ignore the project's architecture.

Allies-specific conversion notes (override Fan IQ bits in that skill):

- Fonts: **Open Runde** already wired in `apps/web/app/layout.tsx`. Do not apply
  Fan IQ `line-sans` / `berlin` classes.
- Strip iOS status bar / home indicator unless the user asks to keep them.
- Full-bleed scaled artboard as required by `$html-to-react-exact`.

---

### 9. Playwright E2E Tests

Every task must include E2E tests using **Playwright Test**.

Do not use the previously discussed custom testing package. Use Playwright directly.

If `@playwright/test` is missing from `apps/web`, add it and a `playwright.config.ts`
that loads feature specs.

Tests should live inside the feature's `tests` directory.

For example:

```text
onboarding/
  tests/
    onboarding.spec.ts
```

The tests must cover the complete user flow rather than testing individual screens in isolation.

For an onboarding task, the test should simulate a real user progressing through onboarding from beginning to end.

Where relevant, tests should verify:

* The correct screen is displayed.
* The expected copy is present.
* User interactions work correctly.
* Buttons navigate to the correct next step.
* Form inputs behave correctly.
* Validation works.
* State persists correctly between screens.
* Back/forward behavior works where applicable.
* The complete flow can successfully reach its expected final state.

Testing is part of the implementation, not an optional step.

Run from `apps/web`:

```bash
bunx playwright test <task>/tests --reporter=line
```

Fix failures until the flow passes. Do not mark the task complete with failing E2E.

---

### 10. Final Verification

Before considering the task complete, verify that:

* The implementation matches the JSON.
* All required screens have been implemented.
* The copy matches the source.
* Components follow the expected structure.
* Reusable components have been extracted appropriately.
* `_images` is in the correct location.
* Shared state uses Zustand.
* No unnecessary global state solution has been introduced.
* Playwright E2E tests exist.
* The complete flow passes its E2E tests.
* The task log accurately reflects what was implemented.

Update `TASK.md` with what actually shipped if the plan changed.

---

### 11. Create the Branch

Once implementation and testing are complete, create the appropriate Git branch.

Before creating or naming the branch, read the project's `ENGINEERING_STYLE.md` and follow the branch naming and engineering conventions defined there.

Do not invent a branch naming convention if the repository already defines one.

Current Interface rule (INT-03): web work uses a `web/` prefix.

```text
web/dev/<task-name>
```

Example: task `onboarding` → `web/dev/onboarding`.

Commit subjects use the same platform marker:

```text
web: add onboarding flow
```

Do not create the branch at the start of the task. Create it after
implementation and tests pass, then commit on that branch.

## Hard bans

- Coding before `TASK.md` exists and copy/flow are validated
- Putting the feature in `apps/mobile` or mixing platforms
- `dangerouslySetInnerHTML` / iframe of design HTML
- `_images` inside `components/`
- Agentic-tester or any custom E2E wrapper instead of Playwright Test
- Redux, Jotai, Recoil, or Context-as-global-store for feature state
- Fan IQ font classes or Fan IQ drawer/toaster primitives
- Inventing copy, destinations, or screens missing from the payload
- Naming the branch `feat/…` without the `web/` platform prefix

## Done response

```text
Task: <task-name>
Branch: web/dev/<task-name>
Status: Ready

Implemented:
- <summary>

Screens:
- <screenId>

Structure:
- apps/web/<task>/…

Testing:
- <n> passed / <n> failed
```

If blocked: current step, blocker, and the `TASK.md` path.
