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
| should-look-like-1 | Look (default ghosty avatar) | Full-width paginated carousel; adjacent Ally heads enter during a swipe but stay off-screen at rest. No colour row before the first valid swipe. Hint: `Swipe then pick a colour`. |
| should-look-like-2 | Look (after swipe) | Colour row visible. Next active so the default avatar is not forced. |
| should-look-like-3 | Look (colour selected) | Checkmark on swatch. Avatar wash + Next use the selected colour. |
| job-description-1 | Job (empty) | Placeholder `What do I handle for you?`. `200 character limit`. Next inactive. |
| job-description-2 | Job (filled) | Counter `N characters left`. Next uses selected colour. |
| personality-page | Personality | Chips: Concise, Quirky, Analytical, Funny. Optional note field. Save opens the Ally handoff. |
| coming-alive | Ally handoff | The selected Ally grows from the persistent question-screen preview, breathes once, and settles into the conversation header. |
| conversation | First conversation | While the first hello is prepared, the selected Ally appears only beside Thinking. When the greeting is ready, that same Ally moves into the compact top-left name header and the reply composer stays anchored at the bottom. |

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
5. Swipe the looping carousel one page from the default ghosty avatar → the next shape settles into the centre and the colour row appears (`should-look-like-2`).
6. Select a colour → selected swatch + Next/avatar wash use that colour (`should-look-like-3`).
7. `Next` → job (`job-description-1`). Next inactive until the user types.
8. Typing enables Next in the selected colour (`job-description-2`). 200 character max.
9. `Next` → personality. Select one or more chips (and/or type a note) to enable Next in the selected colour.
10. Saving personality opens the coming-alive handoff, then shows the Ally only beside Thinking while the first hello is prepared. Once ready, that same Ally moves into the top-left name header.
11. The save-your-Ally sheet keeps waitlist capture available; a successful join resolves to the See you soon state.
12. Back from name returns to welcome. Later backs return to the previous step. URL stays `/onboarding`.

Assumption: HTML face `placehold.co` images are invalid placeholders — use real ally SVGs, not those URLs.

## Implementation plan

1. Feature folder `apps/web/onboarding/` with Zustand store and screen components.
2. Shared chrome: artboard, back, Next, progress ring in `apps/web/components/`.
3. Convert each HTML screen to responsive TSX; preserve the authored mobile geometry while deriving horizontal sizing from viewport insets; strip iOS chrome; Open Runde.
4. One route: `/onboarding`. Welcome CTA switches the Zustand step.
5. Playwright covers the full happy path and CTA gates from `/onboarding`.

Shipped: one route `/onboarding`, Zustand store (welcome → name → look → job → personality), screen components, shared chrome.

Responsive layout aligned to the Figma frames:
- The onboarding artboard fills the dynamic viewport; it does not scale a fixed `375×812` canvas.
- Shared chrome uses `top: 68px` with `20px` horizontal insets; the progress ring is right-anchored.
- Headings use `top: 132px` with `20px` horizontal insets.
- The Next CTA is right/left inset by `20px`, anchored with `bottom: 100px`, and has a `48px` minimum height. At a `375px` viewport it resolves to the authored `335px` width.
- The centered name value uses Open Runde `28px / 600`, `100%` line-height, and `-1px` letter spacing.
- The look screen keeps dots at `top: 522`, the colour row at `top: 622`, and the hint at `top: 646` with an `18px` swatch gap.
- The look carousel spans the viewport width, uses one viewport per page so adjacent Allies begin fully off-screen, keeps three repeated copies for seamless wraparound, and uses Motion's spring drag settling. Only the adjacent pages are revealed during a swipe; the resting state shows one static Ally over a fixed colour shell.
- The look screen's selected shell is `164.2px`; the normal `160px` Ally canvas produces the authored approximately `110px` artwork. The live top preview keeps a `40px` shell with the normal shape artwork at approximately `27px`, rather than scaling the full SVG canvas into the shell.
- The question-screen Ally and the conversation handoff share the `onboarding-ally` Motion layout id. The coming-alive hero uses the same selected shape and colour, then the shared Ally settles into a `40px` conversation header avatar without remounting a different visual identity.
- Job and personality keep the editor at `top: 403` with `20px` horizontal insets and the character counter at `top: 671`.
- Personality chips sit at `top: 355` (`8×24` padding, `rgba(255,45,85,0.1)`).
- Unselected carousel artwork is static and transparent. Selected colour is a fixed outer `164.2px` circle; the face remains centred inside it and colour does not cover the face. The small live preview uses a `40px` shell.
- Headings use Open Runde `24px / 700`, `100%` line-height, and `-1px` letter spacing.
- Step changes and taps use a spring/bounce.
- Coming-alive and conversation transitions use Motion layout springs with `AnimatePresence`; reduced-motion users skip the pulse and the staged delay while retaining the final state.

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
| Fluid viewport artboard | `apps/web/components/artboard.tsx` | All screens |
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
