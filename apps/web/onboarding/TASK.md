# onboarding

## Goal

Let a new user make their first ally: name it, choose a look and colour, write a job description, and pick a personality.

## What the JSON is asking us to build

A first-ally onboarding flow on **`/onboarding`**. The welcome screen ends with **Make your first ally**, which starts name → look/colour → job → personality on the same route. Several Figma frames are states of the same screen (empty vs filled, inactive vs active CTA, colour unselected vs selected).

## Screens

| screenId | Role in the flow | Notes (state / variant) |
|---|---|---|
| welcome | Entry on `/onboarding` | Existing welcome wipe. CTA **Make your first ally** starts the make-ally steps in place. |
| what-you-want-1 | Name ally (empty) | Placeholder `give it a name`. Next inactive `#d9d9d9`. |
| what-you-want-2 | Name ally (filled) | Typed name `#ff5800`. Next `#ff5800`. |
| should-look-like-1 | Look (default avatar) | Next inactive until the user swipes once. Hint: `Swipe then pick a colour`. |
| should-look-like-2 | Look (after swipe) | Colour row visible. Next active so the default avatar is not forced. |
| should-look-like-3 | Look (colour selected) | Checkmark on swatch. Avatar wash + Next use the selected colour. |
| job-description-1 | Job (empty) | Placeholder `What do I handle for you?`. `200 character limit`. Next inactive. |
| job-description-2 | Job (filled) | Counter `N characters left`. Next uses selected colour. |
| personality-page | Personality | Chips: Concise, Quirky, Analytical, Funny. Optional note field. End of this payload. |

## Copy

### welcome

- Heading: (existing welcome wipe copy)
- Buttons: `Make your first ally` — starts the make-ally steps on `/onboarding`

### what-you-want-1 / what-you-want-2

- Heading: `What do you want to name your ally?`
- Inputs: placeholder `give it a name` (empty). Filled example in HTML: `Sally Morano`
- Buttons: `Next`

### should-look-like-1 / 2 / 3

- Heading: `What should I look like?`
- Other (state 1): `Swipe then pick a colour`
- Buttons: `Next`

### job-description-1 / job-description-2

- Heading: `What is my job description?`
- Inputs: placeholder `What do I handle for you?`
- Other: `200 character limit` / `{n} characters left`
- Buttons: `Next`
- Filled example: `i want you to check my email every hour for payments receipts from all my banks, build my budget for the month, i don’t want to spend more than $200 weekly. you should keep me in check.`

### personality-page

- Heading: `What should my personality be?`
- Inputs: placeholder `What do I handle for you?`
- Other: `200 character limit`
- Chips: `Concise`, `Quirky`, `Analytical`, `Funny`
- Buttons: `Next`

## User flow

1. Entry: welcome on `/onboarding`
2. `Make your first ally` → sign-in page, then that CTA → name screen (`what-you-want-1`) on the same URL
3. Typing a name turns the name and Next `#ff5800` (`what-you-want-2`). Empty name keeps Next inactive.
4. `Next` → look screen (`should-look-like-1`). Next inactive.
5. Swipe the avatar once → Next becomes active; colour row appears (`should-look-like-2`).
6. Select a colour → selected swatch + Next/avatar wash use that colour (`should-look-like-3`).
7. `Next` → job (`job-description-1`). Next inactive until the user types.
8. Typing enables Next in the selected colour (`job-description-2`). 200 character max.
9. `Next` → personality. Select one or more chips (and/or type a note) to enable Next in the selected colour.
10. Back from name returns to welcome. Later backs return to the previous step. URL stays `/onboarding`.

Assumption: HTML face `placehold.co` images are invalid placeholders — use real ally SVGs, not those URLs.

## Implementation plan

1. Feature folder `apps/web/onboarding/` with Zustand store and screen components.
2. Shared chrome: artboard, back, Next, progress ring in `apps/web/components/`.
3. Convert each HTML screen to TSX with exact 375×812 metrics; strip iOS chrome; Open Runde.
4. One route: `/onboarding`. Welcome CTA switches the Zustand step.
5. Playwright covers the full happy path and CTA gates from `/onboarding`.

Shipped: one route `/onboarding`, Zustand store (welcome → name → look → job → personality), screen components, shared chrome.

Layout locked from HTML + user correction:
- Next is always `24px` from the bottom (`812 - 48 - 24 = 740`).
- Colour row sits `36px` above Next (`top: 656`), `18px` swatch gap.
- Unselected avatar is `160×160`. Selected colour is the outer `160` circle; the face is `109×109` inside it — colour does not cover the face.
- Headings use `24 / 32` line-height.
- Personality chips sit at `top: 311` (`8×24` padding, `rgba(255,45,85,0.1)`); note field at `359`.
- Step changes and taps use a spring/bounce.

## Component organization

```text
apps/web/onboarding/                 # task log + source HTML
  TASK.md
  payload.json
  _html/
apps/web/app/(onboarding)/
  _images/
  _components/                       # screens live here
  _store/onboarding-store.ts
  _tests/onboarding.spec.ts
  onboarding/page.tsx                # /onboarding — welcome + make-ally steps
apps/web/components/                 # shared chrome
```

## Reusable components

| Pattern | Shared location | Used by |
|---|---|---|
| Full-bleed 375 artboard | `apps/web/components/artboard.tsx` | All screens |
| Pill Next CTA | `apps/web/components/next-button.tsx` | Name, look, job, personality, sign-in |
| Circular back | `apps/web/components/back-button.tsx` | All steps after entry |
| Circular progress | `apps/web/components/progress-ring.tsx` | Look, job, personality |

## Shared state

| Field | Why Zustand | Screens that read/write it |
|---|---|---|
| step | Survives transitions | index + all screens |
| name | Used after name step | name-ally |
| avatarIndex | Look carousel | look-like |
| hasSwipedAvatar | Gates Next on look | look-like |
| color | Accents later CTAs | look, job, personality |
| job | Job copy | job-description |
| personalities | Selected chips | personality |
| personalityNote | Optional note | personality |

## E2E scenarios

- Happy path: `/onboarding` CTA → personality with name, swipe, colour, job, and a trait
- URL stays `/onboarding` for every step
- Next stays inactive on name / look / job until the described gate
- Typed name turns orange; selected colour tints later Next buttons
- Back returns to the previous step
