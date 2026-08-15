# Task log template

Write this file as `apps/web/<task>/TASK.md` **before** converting HTML or
editing feature code. Fill every section. Do not leave placeholders.

~~~~markdown
# <task-name>

## Goal

<One or two sentences: what we are building and for whom.>

## What the JSON is asking us to build

<Plain-language summary of the payload. Not a screen-by-screen dump.>

## Screens

| screenId | Role in the flow | Notes (state / variant) |
|---|---|---|
| <id> | <entry / step / confirmation> | <e.g. empty vs filled CTA> |

## Copy

For each screen, list headings, body, labels, placeholders, buttons, and
helper text exactly as in the HTML / description.

### <screenId>

- Heading:
- Body:
- Inputs:
- Buttons:
- Other:

## User flow

1. Entry: `<screenId>`
2. On `<control>` → `<screenId>`
3. …

Include inactive/active button rules, swipe gates, and color inheritance.

## Implementation plan

1. …
2. …

## Component organization

```text
apps/web/<task>/
  components/
    index.tsx
    <screen>.tsx
  store/
    <task>-store.ts
  tests/
    <task>.spec.ts
  _images/
  _html/
apps/web/components/   # shared only
apps/web/app/(<task>)/…/page.tsx  # thin route
```

## Reusable components

| Pattern | Shared location | Used by |
|---|---|---|
| <e.g. primary CTA> | `apps/web/components/…` | <screens> |

## Shared state

| Field | Why Zustand | Screens that read/write it |
|---|---|---|
| <name> | <survives transitions / multi-screen> | <ids> |

Local React state is only for isolated UI (hover, input caret, one-screen
animation).

## E2E scenarios

- Happy path: start → last screen
- Inactive CTA stays inactive until the described gate (type / swipe / select)
- Typed name / selected color persist onto later screens
- Back/forward where the flow provides it
~~~~
