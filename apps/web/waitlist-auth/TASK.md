# waitlist-auth

## Goal

Replace the post-greeting waitlist email modal with the Create-your-account overlay, then hold on the welcome screen after a fake ChatGPT or Google signup. Works on mobile and desktop.

## What the JSON is asking us to build

Three Figma states for the waitlist gate after the Ally greets the user. `auth-allies-1` is the Google-only overlay. `auth-allies-2` is the live overlay with ChatGPT and Google. `welcome-allies-1` is the short welcome hold after signup. Auth is not wired; either CTA goes to welcome. After the 3s welcome hold we show `allow-notifications-allies`. Either CTA continues to the existing Follow on X screen; notifications are not wired.

## Screens

| screenId | Role in the flow | Notes (state / variant) |
|---|---|---|
| auth-allies-1 | Overlay variant | Google-only. Converted, not the live gate. |
| auth-allies-2 | Live overlay | ChatGPT + Google. Opens when the user tries to type after the greeting. |
| welcome-allies-1 | Post-signup hold | Personalized heading, 3s animated mark, then notifications. |
| allow-notifications-allies | Permission prompt | After welcome. Either CTA goes to Follow on X. |

## Copy

### auth-allies-1

- Heading: `Create your account`
- Body: `Your ally has been saved but you need to set up an account to use it.`
- Buttons: `Sign up with Google`
- Other: `By continuing, you agree to our Terms of Service and have read our Privacy Policy`

### auth-allies-2

- Heading: `Create your account`
- Body: `Your ally has been saved but you need to set up an account to use it.`
- Buttons: `Sign up with ChatGPT`, `Sign up with Google`
- Other: `By continuing, you agree to our Terms of Service and have read our Privacy Policy`

### welcome-allies-1

- Heading: `Looking good, {name}` (HTML example: `Looking good, Tolani`)
- Body: `We’re done with the basics, one more thing`

### allow-notifications-allies

- Heading: `Keep up with your allies`
- Body: `Allow notifications so you can track tasks, reminders, and reach goals faster`
- Buttons: `I’ll do this later`, `Allow notifications`

Background chat copy in the auth HTML (`Sally Morano`, long greeting) is the existing waitlist chat, not overlay copy.

## User flow

1. Entry: existing `/onboarding` waitlist chat after the Ally greeting.
2. Focus or type in the composer → `auth-allies-2` overlay over the chat.
3. Close (X) dismisses the overlay. The next type/focus opens it again until signup.
4. `Sign up with ChatGPT` or `Sign up with Google` → Ally mark moves to the center, overlay fades, `welcome-allies-1` appears.
5. Welcome holds ~3s with the usual Ally animation (instant if reduced motion).
6. `allow-notifications-allies`. `I’ll do this later` or `Allow notifications` → Follow on X.

## Implementation plan

1. Save payload and convert all three HTML files with `html_to_jsx.mjs`.
2. Extract the 351×462 overlay card from `auth-allies-2`; do not ship the phone frame.
3. Replace the email save modal with the auth overlay.
4. Shared `layoutId` on the Ally mark for the center transition.
5. Welcome uses the user’s Ally name and selected color.
6. Desktop: same card metrics, centered on wide viewports; welcome stays full-bleed.
7. Playwright covers greeting → overlay → either CTA → welcome → completion.

## Component organization

```text
apps/web/waitlist-auth/
  TASK.md
  payload.json
  _html/
  _images/screens/
apps/web/app/(onboarding)/
  _components/auth-overlay.tsx
  _components/auth-welcome.tsx
  _components/waitlist-preview.tsx
  _images/from-html/waitlist-auth/
  _tests/waitlist-auth.spec.ts
apps/web/components/   # existing Artboard / AllyAvatar
```

## Reusable components

| Pattern | Shared location | Used by |
|---|---|---|
| Ally mark | `apps/web/components/ally-avatar.tsx` | overlay, welcome |
| Artboard | `apps/web/components/artboard.tsx` | waitlist screens |

## Shared state

| Field | Why Zustand | Screens that read/write it |
|---|---|---|
| name, shape, color | Already in onboarding store | overlay mark, welcome heading |
| authPhase (local) | Isolated to waitlist preview | overlay / welcome / complete |

Local React state owns overlay open, fake-signup hold, and the 3s timer.

## E2E scenarios

- After greeting, typing opens Create your account with both signup buttons
- Close dismisses the overlay
- ChatGPT or Google goes to `Looking good, {name}`
- After the welcome hold, Follow on X is visible
- Overlay and welcome render at mobile and desktop widths

## Shipped

Composer focus, change, or submit after coming-alive opens `auth-allies-2`. Either provider CTA morphs the Ally mark to center and holds `welcome-allies-1` for 3s, then `allow-notifications-allies`. Either notifications CTA goes to Follow on X. `auth-allies-1` stays converted only.
