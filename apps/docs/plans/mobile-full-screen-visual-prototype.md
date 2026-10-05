# Mobile Full-Screen Visual Prototype Plan

## Feature Overview

- Problem: The app implements the M2 create-and-talk slice, but M3 and M4
  destinations cannot yet be reviewed as one navigable mobile product.
- Target users: Product, Design, and internal engineering reviewers.
- Source docs/specs: Nabu product philosophy, first product requirements,
  product design specification, Interface roadmap, mobile implementation
  handoff, the existing M2 app-surface plan, Expo SDK 57 Router documentation,
  and `ENGINEERING_STYLE.md`.
- Success outcome: A reviewer can move through every accepted M2 through M4
  destination in the mobile app. Future behavior is visibly marked as a design
  preview and does not claim durable state or completed Cloud capability.

## User Stories

1. As a reviewer, I want three stable roots for Allies, Activity, and Settings,
   so that the intended app structure is visible.
2. As a reviewer, I want to open every planned detail state, so that Product and
   Design can critique a complete screen journey before backend work starts.
3. As an engineer, I want unfinished behavior to stay explicit, so that a visual
   prototype cannot be mistaken for working persistence, authorization, billing,
   integrations, approvals, routines, or deletion.

## Scope

### In Scope

- Shared bottom navigation for Allies, Activity, and Settings.
- Activity attention feed with result, waiting, approval, failure, and routine
  outcome examples.
- Settings root with Profile, Preferences, Connections, Usage and Billing,
  Privacy and Sessions, and a complete screen map.
- Connection detail previews.
- Ally settings with identity, responsibilities, routines, access, and deletion
  review screens.
- Focused M4 approval, usage-limit, activity-receipt, critical-failure, and
  deletion states.
- Honest Preview labels, disabled future actions, accessibility labels, safe
  areas, and existing Open Runde/Allies visual language.

### Out of Scope

- New Cloud methods, persistence, mutations, local mock databases, or fake
  success states.
- Functional approval, billing, integration, routine, responsibility, usage,
  notification, session, or deletion behavior.
- New dependencies, native configuration, app-version changes, OTA publishing,
  or PR merge.

### Dependencies and Assumptions

- Expo Router remains the navigation owner.
- Existing fonts, `expo-symbols`, React Native primitives, Ally artwork, and
  current route/session guard are sufficient.
- Static preview content is allowed only on screens that visibly identify
  themselves as visual previews.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `apps/mobile/src/features/app-preview/screen-map.ts` | `getPreviewScreen` | `(family: PreviewFamily, id: string) => PreviewScreen | null` | Allowlisted family and ID | Static screen descriptor or `null` | None |
| `apps/mobile/src/features/app-preview/preview-ui.tsx` | `PreviewPage` | `(props: PreviewPageProps) => ReactElement` | Title, optional copy, content, navigation state | Safe-area screen | Route navigation only |
| `apps/mobile/src/features/app-preview/preview-ui.tsx` | `AppBottomNav` | `({ active }: { active: RootDestination }) => ReactElement` | One of Allies, Activity, Settings | Three accessible actions | Replaces the current root route |

### API and Transport Contracts

Not applicable. This change adds no network operation and changes no Cloud
request or response.

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `PreviewScreen` | `apps/mobile/src/features/app-preview/screen-map.ts` | `id`, `family`, `title`, `summary`, `status`, `tone`, `details`, `actions` | All display fields required; actions optional | IDs are unique inside each family; action paths are internal | Static visual-only data; remove each descriptor when its real feature owns the route |

### Frontend Interaction Shapes

| UI entry point | Action | State and transitions | API mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| Bottom navigation | `router.replace(root)` | Active root changes immediately | None | Protected by the existing session route guard |
| Activity row | `router.push(detail)` | Feed to focused state | None | Preview label states that data is illustrative |
| Settings row | `router.push(section)` | Settings to section or current Account | None | Future controls are disabled and labelled Preview |
| Ally settings row | `router.push(section)` | Overview to one Ally review surface | None | No mutation or fake save state |

## Phases

### Phase 1 - Shared preview shell and route guard

- Goal: Add one design system and make future roots authenticated routes.
- Work items: Add shared screen, row, status, action, and bottom-navigation
  primitives. Extend the protected-route predicate for Activity and Settings.
- Impacted files: `features/app-preview/preview-ui.tsx`, `lib/session/session-route.ts`,
  and its focused test.
- Exit criteria: Signed-out users cannot open preview routes; signed-in users can
  switch among all three roots.

### Phase 2 - Activity and trust-state walkthrough

- Goal: Make the attention feed and every accepted focused work state reviewable.
- Work items: Add Activity root and one dynamic detail route backed by allowlisted
  descriptors for result, waiting, approval, failure, and routine outcome.
- Impacted files: `app/activity/index.tsx`, `app/activity/[item].tsx`, and
  `features/app-preview/screen-map.ts`.
- Exit criteria: Every activity row opens a distinct screen and no action claims
  to update Cloud.

### Phase 3 - Global Settings walkthrough

- Goal: Make every accepted account-wide destination navigable.
- Work items: Add Settings root, dynamic section route, connection detail route,
  and links to the existing Account screen.
- Impacted files: `app/settings/index.tsx`, `app/settings/[section].tsx`, and
  `app/settings/connection/[service].tsx`.
- Exit criteria: Profile, Preferences, Connections, Usage and Billing, Privacy
  and Sessions, usage-limit, and screen-map views are reachable.

### Phase 4 - Ally settings walkthrough

- Goal: Make the relationship-specific settings and M4 deletion path visible.
- Work items: Add Ally settings overview and dynamic review sections for identity,
  responsibilities, routines, access, and deletion. Link the existing identity
  screen and Settings screen to the preview.
- Impacted files: `app/allies/[allyId]/settings/index.tsx`,
  `app/allies/[allyId]/settings/[section].tsx`, existing Ally identity, and
  Settings root.
- Exit criteria: A reviewer can traverse each Ally-specific surface without a
  real Ally or a fake persistence layer.

### Phase 5 - Verification and handoff

- Goal: Leave a reviewable, traceable change.
- Work items: Add one screen-map invariant test, update README and Nabu, run the
  relevant test suite, lint, typecheck, exports, commit, push, and update PR #14.
- Impacted files: `screen-map.test.ts`, `apps/mobile/README.md`, and canonical
  Nabu mobile/product notes.
- Exit criteria: Checks pass; the branch is pushed; no OTA is published.

## Acceptance Criteria

1. Allies, Activity, and Settings are visible and navigable root destinations.
2. The Activity feed includes results, waiting work, approvals, failures, and
   routine outcomes.
3. Activity detail screens do not expose runtime or raw Hermes language.
4. Settings includes Profile, Preferences, Connections, Usage and Billing,
   Privacy and Sessions, and the screen map.
5. Profile opens the current real Account screen.
6. Connection previews show access by Ally without claiming a connection exists.
7. Ally settings includes identity, responsibilities, routines, access, and delete.
8. Responsibility and routine screens remain review surfaces, not manual editors.
9. Delete explains impact and cannot delete anything.
10. Approval actions are visibly disabled as Preview behavior.
11. Usage-limit and critical-failure states explain the next available action.
12. Every future screen identifies itself as a visual preview.
13. New routes are protected by the native session guard.
14. The implementation adds no package or native configuration.
15. README and Nabu record that these screens are visual scaffolds, not working
    product capability.

## Frontend Considerations

### Data Path

- User action entry: Shared root navigation or preview list row.
- Client route/component: Expo Router routes under `app/activity`, `app/settings`,
  and `app/allies/[allyId]/settings`.
- Backend endpoint: None.
- Response to UI mapping: An allowlisted static descriptor maps directly to
  presentational primitives.
- Error path: An unknown dynamic ID renders an honest “Preview not found” screen
  with a safe route back.

### State Management Considerations

- React local state is used only where a visual input needs focus or typing.
- Static descriptor content has no store and no persistence.
- Existing Cloud and session state remains authoritative for implemented screens.
- Route parameters select an allowlisted descriptor. They never become display
  copy without validation.

## Test Plan

- Unit tests: Assert unique descriptor IDs, required screen families, safe internal
  action paths, and protected Activity/Settings routes.
- Regression checks: Existing onboarding, auth, Workspace, conversation, and
  account tests.
- Manual verification: Walk the screen map at common Android dimensions, verify
  safe areas, scroll behavior, disabled actions, keyboard dismissal, and back paths.
- Commands: `bun run test:run`, `bun run lint:mobile`, `bun run typecheck`,
  `bun run bundle:mobile`, Android Expo export, and `git diff --check`.

## Risks and Mitigations

- Risk: Reviewers mistake illustrative data for Cloud truth.
- Mitigation: Every future surface has a visible Preview label and future actions
  remain disabled.
- Risk: A large set of route files creates duplicated UI.
- Mitigation: Dynamic family routes and one shared preview UI own the composition.
- Risk: The visual prototype becomes a second product architecture.
- Mitigation: Routes follow the accepted Nabu information architecture and are
  deleted or replaced as each real feature receives a contract.
- Rollback/fallback: Remove the preview route families and bottom-navigation calls;
  the implemented M2 routes and Cloud behavior remain unchanged.
