# Mobile conversation screen layout and presence plan

## Feature Overview

- Problem: The logged-in mobile conversation places the opening message too high, renders several Ally blobs, does not keep the single active blob below the latest content, and loses the latest content when the keyboard or typewriter changes the layout.
- Target users: Mobile users viewing an Ally conversation after setup.
- Source docs/specs: Nabu `projects/allies/index.md`, `projects/allies/engineering/specs/conversation-and-streaming.md`, `projects/allies/product/allies-product-design-spec.md`, `ENGINEERING_STYLE.md`, and Expo SDK 57 documentation.
- Success outcome: The logged-in conversation matches the onboarding message position, shows one 33.6px Ally blob below the latest message, shows the existing Thinking shimmer beside that same blob while replying, and follows new content without fighting manual history scrolling.

## User Stories

1. As a mobile user, I want the conversation copy to start in the same position as onboarding, so that the handoff feels continuous.
2. As a mobile user, I want one Ally blob to sit below the current conversation content, so that it moves down naturally as the reply grows and remains on the left after I send a message.
3. As a mobile user, I want the latest reply and composer to remain reachable while content grows or the keyboard opens, so that I can follow the conversation and continue typing.

## Scope

### In Scope

- Update the local logged-in mock conversation presentation.
- Remove the identity row and per-message Ally previews.
- Render one trailing Ally status row with idle/thinking states.
- Follow the latest content on content growth, message changes, keyboard/layout changes, and send/focus actions while respecting manual scrolling.
- Increase the chat Ally preview from 28px to 33.6px.
- Add a focused pure geometry test; verify rendered structure and keyboard behavior manually on Android and iOS.

### Out of Scope

- Cloud conversation transport, persisted history, activity replay, or authentication.
- Changes to onboarding, the mock state provider, the route, theme tokens, or deleted parallel files.
- Claiming that an entire long message can remain visible above the keyboard on a small device.

### Dependencies and Assumptions

- `MockConversationScreen` remains the presentation boundary for the current mobile prototype.
- `OnboardingAllyPreview`, `ShinyText`, `KeyboardAvoidingView`, and `ScrollView` remain the existing primitives.
- Expo SDK 57 targets React Native 0.86 and the current mobile package already uses those versions.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `apps/mobile/src/features/mock/mock-conversation-screen.tsx` | `MockConversationScreen` | `MockConversationScreen(props: MockConversationScreenProps): JSX.Element` | Existing Ally identity and navigation callback; draft remains bounded by the existing input | Rendered conversation screen | Local mock send flow, keyboard dismissal, bounded follow-latest scrolling |

### API and Transport Contracts

Not applicable. This presentation-only change does not add or change an HTTP, Cloud, or streamed-event contract.

### Schema and Data Shapes

Not applicable. Existing `MockAlly` and `MockMessage` shapes remain unchanged.

### Frontend Interaction Shapes

| UI entry point | Hook / action signature | State shape and transitions | API input/output mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| Conversation timeline | `ScrollView` layout/content callbacks | `followLatest: true` while near bottom; false after the user scrolls away | Message state -> normal-flow message list -> trailing Ally status | New content follows only while the user is near the bottom |
| Send composer | Existing `handleSend(): void` | Draft -> mock user message -> replying -> assistant reply | Existing `mock.sendMessage` contract | Existing disabled and keyboard-dismiss behavior remains |
| Ally status | `ConversationAllyStatus(ally, isReplying)` | `idle <-> thinking` | Existing Ally shape/color -> `OnboardingAllyPreview` | One accessible Ally preview is always present; Thinking text appears only while replying |

## Phases

### Phase 1 - Conversation presentation

- Goal: Match onboarding positioning and establish one trailing Ally presence.
- Work items: Reuse onboarding spacing constants, remove the identity/per-message previews, add the trailing status row, and apply the 1.2 size multiplier.
- Impacted files: `apps/mobile/src/features/mock/mock-conversation-screen.tsx`.
- Exit criteria: The source contains one status-owned Ally preview, no visible name row, and the status row follows all messages.

### Phase 2 - Follow-latest behavior and proof

- Goal: Keep the latest content reachable during typewriter growth, reply changes, and keyboard layout changes without overriding manual history scrolling.
- Work items: Add a small near-bottom geometry helper, schedule bounded `scrollToEnd` calls from content/layout/message changes and send/focus, then test the helper.
- Impacted files: `apps/mobile/src/features/mock/mock-conversation-screen.tsx`, `apps/mobile/src/features/mock/mock-conversation-screen.test.ts`.
- Exit criteria: Focused tests cover the geometry rule and structure; mobile lint, typecheck, bundle, full tests, and diff validation pass.

## Acceptance Criteria

1. The first logged-in conversation message starts at the onboarding-equivalent vertical offset of 78px below the safe-area top: 36px top padding + 24px header reserve + 18px greeting gap.
2. The Ally name and identity row are absent from the logged-in conversation timeline.
3. Exactly one Ally preview is rendered in the logged-in conversation, after the latest message.
4. The preview is 33.6px, remains left-aligned, and uses idle when settled and thinking while replying.
5. The existing ShinyText Thinking label uses the same status row and does not create a second blob.
6. The trailing preview moves down as the assistant message typewriter grows and appears below a newly sent user message.
7. Auto-scroll follows new content and keyboard/layout changes only while the user remains near the bottom.
8. The existing reduced-motion, safe-area, composer, and mock-send behavior remains intact.

## Frontend Considerations (if applicable)

### Data Path

- User opens `apps/mobile/src/app/allies/[allyId]/index.tsx`.
- The route passes the selected `MockAlly` to `MockConversationScreen`.
- `useMockApp().getConversation` supplies messages; the existing provider appends the user message and delayed mock reply.
- The screen renders the messages and one status row, then keeps the composer outside the scroll view.

### State Management Considerations

- Mock provider state remains the source of truth for messages and reply state.
- The screen owns only draft/composer state, typewriter progress, scroll ref, and the derived follow-latest preference.
- Follow-latest is disabled when the user scrolls more than the existing small bottom threshold away from the end.
- No new persistence, cache, API state, or dependency is introduced.

## Test Plan

- Unit tests: Verify the 78px onboarding-equivalent offset and the near-bottom formula `contentHeight - (offsetY + viewportHeight) <= threshold`.
- Manual structure checks: Verify one trailing Ally preview, no identity row, idle/thinking states, and the existing ShinyText Thinking label on Android and iOS.
- Regression checks: Existing onboarding preview and mock app tests remain green.
- Manual verification checklist: Open a completed Ally, watch the opening copy position, send a message, observe the blob below the user message and Thinking shimmer, watch the blob move below a growing reply, scroll upward and confirm follow-latest does not steal position, then open the keyboard and confirm the latest content and composer remain reachable.
- Commands:
  - `bun x vitest run apps/mobile/src/features/mock/mock-conversation-screen.test.ts apps/mobile/src/features/mock/mock-app.test.ts apps/mobile/src/features/onboarding/onboarding-preview.test.ts`
  - `bun run lint:mobile`
  - `bun --filter mobile typecheck`
  - `bun run bundle:mobile`
  - `bun run test:run`
  - `git diff --check`

## Risks and Mitigations

- Risk: The current route is a local mock, not the Cloud-backed conversation contract.
- Mitigation: Keep the change presentation-only and preserve the existing provider API.
- Risk: A 4000-character message cannot all remain visible above a mobile keyboard.
- Mitigation: Follow the latest content and keep the composer/status tail reachable; allow normal scrolling for older content.
- Rollback/fallback: Revert the two scoped files; no persisted data or backend contract changes are made.
