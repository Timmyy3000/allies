---
title: Allies Interface Development Guide
status: working guide
audience: Allies interface engineers and agents during initial engineering intake
canonical_nabu: projects/allies/engineering/guides/interface-development.md
---

# Allies Interface Development Guide

## Status and purpose

This guide is the starting point for engineering work in `allies-interface`. It
explains how to get oriented, where interface code belongs, and which boundaries and
conventions apply to the web and mobile clients.

It is narrower than a complete frontend handbook. Use it to make a safe,
understandable first change in the web or mobile client.

When this guide and the code disagree, the code and its tests describe the current
implementation. If the difference is intentional, record it in the decision log and
update this guide when the convention changes.

## First intake: read in this order

1. Read this guide and the repository `README.md`.
2. Read the root `package.json` and `bun.lock` to understand workspace scripts and
   the exact dependency baseline.
3. Read the nearest `AGENTS.md` before inspecting or changing an application:
   - `apps/web/AGENTS.md` for Next.js work;
   - `apps/mobile/AGENTS.md` for Expo work.
4. Before writing framework code, read the exact installed framework guidance:
   - Next.js guidance under `node_modules/next/dist/docs/` for web changes;
   - Expo documentation for SDK `57.0.0` for mobile changes.
5. Read the relevant Allies knowledge notes:
   - `projects/allies/index.md`;
   - `projects/allies/docs/05-technical-architecture.md`;
   - `projects/allies/engineering/specs/conversation-and-streaming.md`;
   - `projects/allies/product/allies-product-philosophy.md`;
   - the product note for the flow being changed.
6. Run the baseline checks before changing code when dependencies are available.
7. Inspect the smallest relevant route, feature, component, and API boundary before
   deciding where the change belongs.

Do not infer interface conventions from the generated Next.js or Expo starter UI.
The current application screens are scaffolding, not accepted product patterns.

## Current repository baseline

`allies-interface` is one Bun workspace and one repository containing two clients:

```text
allies-interface/
├── apps/
│   ├── web/       # Next.js web client
│   └── mobile/    # Expo / React Native client
├── packages/     # reserved for code with real cross-client ownership
├── docs/
└── package.json
```

The current baseline is:

- Bun `1.2.20`;
- Next.js `16.2.12` and React `19.2.4` for web;
- Expo `57.0.9`, Expo Router `57.0.9`, React Native `0.86.2`, and React `19.2.3`
  for mobile;
- TypeScript strict mode in both applications;
- Tailwind CSS `4` in the web application;
- file-based routing through the Next.js App Router and Expo Router;
- root scripts for web development, mobile development, linting, and the web build.

The repository does not yet have a feature directory, API client, component library,
state library, or test suite. Introduce these structures when a real feature needs
them. Do not copy them from a generic starter architecture.

## Product and system boundaries

The Allies architecture gives the Interface these boundaries:

- The Interface talks only to Allies Cloud.
- The Interface never connects directly to Foundry, Hermes, Fly Machines, tenant
  volumes, or runtime addresses.
- Cloud owns customer-facing Allies, conversations, messages, authorization, and
  the visible product timeline.
- Foundry owns runtime execution truth behind Cloud.
- The Interface owns rendering, navigation, drafts, presentation state, local
  interaction state, and reconnecting to Cloud streams.
- Cloud cursors and replayable product events are the recovery boundary. The client
  must not reconnect to an old Hermes stream.
- Each Ally has one continuous user-facing conversation initially. Different Allies
  may stream concurrently; a later turn for the same Ally waits.

Use product language in the interface: Ally, job, responsibility, routine, approval,
handoff, result, activity, and access. Runtime terms such as profile, execution,
attempt, lease, Machine, and Hermes session are implementation details unless a
technical view explicitly needs them.

## Intake a change before implementing it

For every new slice, write down:

- the user outcome and the Ally responsibility it supports;
- whether the change belongs on web, mobile, or both;
- the Cloud data or API contract it consumes;
- the states the user can observe: loading, empty, active, waiting for approval,
  completed, failed, stopped, and disconnected where relevant;
- what the Interface owns locally and what Cloud remains authoritative for;
- the accessibility, keyboard, touch, reduced-motion, and responsive requirements;
- the targeted checks that prove the behavior.

Do not start by adding a generic component or global store. Start from the user
flow, identify the owning feature, and trace the smallest vertical slice through
route or screen, feature logic, Cloud boundary, and visible states.

## Code organization

The applications should keep framework routing separate from feature behavior:

```text
apps/web/
├── app/                 # routes, layouts, loading, and error boundaries
├── features/            # feature-owned views, hooks, and data adapters
├── components/ui/       # generic visual primitives with no product ownership
└── lib/                 # cross-cutting client, auth, and utility code

apps/mobile/src/
├── app/                 # Expo Router routes and layouts
├── features/            # feature-owned screens, hooks, and data adapters
├── components/ui/       # generic native/shared visual primitives
└── lib/                 # cross-cutting client, auth, and utility code
```

Use this shape as the default. A small feature may remain close to its route until it
has enough behavior to justify a feature folder.

### Routes and screens

Routes and screens compose a feature. They should not contain large workflows,
network clients, or duplicated product rules.

They may:

- resolve route parameters;
- choose the page or screen composition;
- connect framework lifecycle to a feature hook;
- render loading, empty, error, and success states.

### Features

A feature owns one understandable user capability, such as creating an Ally,
viewing a conversation, or reviewing an approval.

A feature may contain:

- feature views;
- user interaction hooks;
- Cloud request functions or adapters;
- feature-specific types;
- tests for the behavior it owns.

Do not create a feature folder for every component. Create one when the capability
has meaningful behavior or appears in more than one route.

### UI components

Generic UI components provide reusable visual behavior without owning a product
workflow. They should receive explicit props and remain unaware of Cloud, Foundry,
Hermes, authentication policy, or Ally-specific business rules.

Product components may live inside a feature when their meaning is specific to that
feature. Reuse is earned by a second real consumer, not assumed in advance.

### Shared packages

The `packages/` workspace is reserved for code with real cross-client ownership.
Share contracts, semantic tokens, and small platform-neutral utilities before
sharing UI implementations. Add a shared UI package only when web and mobile have
two concrete consumers with the same behavior and the platform abstraction remains
clear.

## Data, state, and communication

Keep these rules for client code:

- Keep all Cloud calls behind an explicit client boundary; presentational components
  do not call `fetch` directly.
- Keep wire DTOs at the Cloud boundary and map them to view models when the UI needs
  a different shape or vocabulary.
- Treat Cloud-persisted data and replayable events as authoritative.
- Keep drafts, open panels, focus, animation state, and other ephemeral interaction
  state local to the feature or screen.
- Use feature-local state. Add a shared or server-state library only when cross-screen
  coordination, caching, or offline behavior creates a demonstrated need.
- Keep optimistic updates limited to actions whose failure and reversal are clear.
- Keep conversation streaming behind a feature-level interface so the transport can
  change without spreading SSE, WebSocket, or fetch-stream details through the UI.
- Reconnect to Cloud with the last Allies cursor, replay missed product events, and
  route events by Allies conversation and execution identifiers before applying
  local sequence order.
- Never expose Hermes credentials, runtime addresses, raw secrets, or unsafe tool
  output to the client.

This guide defines the client boundary, not Cloud's wire format, live transport,
authentication flow, or test framework. Document those details with the relevant
contract when they are implemented.

## Interface design principles

The interface should feel warm, calm, capable, and alive. It should also be
understandable, personal, and purposeful. It should not feel like an infrastructure
dashboard.

Apply these rules to each screen:

- Hide infrastructure, but preserve control. Users should understand what the Ally
  did, what information it used, what changed, what needs approval, and how to stop
  or reverse it.
- Show understandable activity instead of an unexplained long-running spinner.
- Use one clear primary purpose per screen or state transition.
- Start with ordinary language and reveal configuration when it becomes useful.
- Make identity functional: an Ally's name, job, responsibilities, memory, files,
  permissions, and activity should feel like one boundary.
- Keep collaboration explicit and show who requested work, who performed it, and
  what information was shared.
- Make authority visible: approval, rejection, stopping, correction, memory control,
  export, and deletion must remain user actions.

### Accessibility and state

Accessibility belongs in the feature from the start. New interface work should
include:

- semantic controls and labels;
- keyboard access on web and appropriate native accessibility roles and labels;
- visible focus or pressed states;
- readable status text that does not rely on color alone;
- useful empty, error, retry, stopped, and disconnected states;
- reduced-motion behavior for meaningful animation;
- touch targets and safe-area handling on mobile;
- responsive layouts that preserve the primary task rather than merely shrinking it.

## Platform-specific intake

### Web

- Use the Next.js App Router structure already present in `apps/web/app`.
- Keep server and client component boundaries intentional. A live interactive or
  browser-only feature should make its client boundary explicit.
- Keep server-only credentials and privileged data out of client components.
- Read the installed Next.js guidance before using a framework API, because this
  repository targets a version with breaking changes from older examples.
- Keep metadata, loading, error, and route composition close to the route; keep
  product behavior in the owning feature.

### Mobile

- Use Expo Router under `apps/mobile/src/app` for navigation and layouts.
- Read the Expo SDK `57.0.0` documentation before using Expo or React Native APIs.
- Treat safe areas, platform differences, keyboard behavior, system back behavior,
  native permissions, and screen-reader labels as part of the feature design.
- Prefer platform-native behavior over forcing web assumptions into the mobile app.
- Share semantics and contracts where useful, but allow web and native compositions
  to differ when their interaction models differ.

## Baseline checks and handoff

Run from the repository root:

```text
bun install --frozen-lockfile
bun run lint
bun run build:web
```

For focused work, also run:

```text
bun run lint:web
bun run lint:mobile
```

Before handoff, confirm:

- the changed surface and ownership boundary are clear;
- the feature does not call Foundry, Hermes, Fly, or runtime services directly;
- loading, empty, active, failure, approval, stopped, and reconnect states are
  handled where relevant;
- no secret or privileged credential reaches client code;
- web and mobile behavior is intentionally shared or intentionally different;
- accessibility and reduced-motion behavior were checked;
- the focused lint/build checks pass;
- the guide or an engineering decision is updated when an accepted convention
  changes.

The current CI runs both linters and builds the web client. Until mobile build
validation and application tests are added to CI, run the mobile lint and targeted
checks locally.

Keep this guide focused on intake and cross-client conventions. Document
feature-specific behavior and contracts with the feature that owns them.
