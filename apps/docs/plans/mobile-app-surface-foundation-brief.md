# Mobile App Surface Foundation Work Brief

## Objective

Deliver the first working signed-in Allies mobile slice toward milestone M2. A tester must be able to create an Ally with the existing onboarding flow, open that Ally, read its Cloud conversation, send a message, see bounded lifecycle activity, and inspect the Ally identity. Map the later M3 and M4 screens without implementing them. Do not claim complete M2 until Cloud adds restart-safe Ally collection discovery.

## Work Type

Feature.

## Users

- Signed-in internal alpha testers.
- Product and engineering reviewers who need an honest view of the current Cloud contract.

## Source References

- Nabu: `projects/allies/index.md`
- Nabu: `projects/allies/docs/01-northstar.md`
- Nabu: `projects/allies/product/allies-product-philosophy.md`
- Nabu: `projects/allies/product/allies-first-product-requirements.md`
- Nabu: `projects/allies/product/allies-product-design-spec.md`
- Nabu: `projects/allies/planning/mvp-to-beta-roadmap.md`
- Nabu: `projects/allies/planning/interface-roadmap.md`
- Nabu: `projects/allies/delivery/feature-map.md`
- Nabu: `projects/allies/engineering/specs/conversation-and-streaming.md`
- Live staging OpenAPI: `https://cloud.staging.yourallies.io/api/v1/openapi.json`
- Expo SDK 57 Router, SecureStore, and SplashScreen documentation.
- `ENGINEERING_STYLE.md`
- `apps/mobile/README.md`

## Accepted Product Shape

### M2 implementation

Use stack navigation. The four destinations are:

1. Allies workspace.
2. Create Ally, which reuses the existing onboarding flow.
3. One continuous conversation for each Ally.
4. Read-only Ally identity summary.

The conversation owns pending, working, activity, retry, failure, and completion presentation. Do not add a separate operations screen.

### M3 map only

Add three future root destinations: Allies, Activity, and Settings. Put Profile under Settings. Activity is an attention feed for results, waiting work, approvals, failures, and routine outcomes.

### M4 map only

Add future approval, usage, deletion, trust, and recovery flows after their product and Cloud contracts are accepted.

## In Scope

- Refresh and pin the accepted staging OpenAPI contract.
- Extend the shared Cloud client with validated Ally, conversation, message, and activity view models.
- Add authenticated request coverage for all accepted workspace, Ally, conversation, message, and activity paths.
- Replace the global signed-in redirect to `/account` with route-aware session guards.
- Add an Allies workspace that shows only real Cloud-fetched Ally records that this app session can address.
- Reuse the current onboarding screens to submit a real `CreateAllyRequest`.
- Keep official onboarding public through the preview reply, then require sign-in before production creation.
- Encrypt unresolved create and message commands with the existing Expo Crypto AES API, store the ciphertext in the app document directory, and keep only the AES key in SecureStore. This record is an unsent command, not product truth. Expire pre-auth create commands after seven days, bind them to the first authenticated user and workspace before submission, and clear all commands on explicit sign-out.
- Generate an idempotency key for Ally creation and each message submission.
- Add one continuous conversation route per Ally.
- Poll conversation and activity snapshots only while Cloud reports `queued`, `in_progress`, or `running` work.
- Stop polling on completion, failure, route blur, or unmount.
- Add a read-only identity summary.
- Preserve account access from the workspace.
- Cover loading, empty, offline, retry, provisioning, pending, completed, and failure states.
- Preserve reduced-motion and accessibility behavior.
- Update the mobile README and Nabu after validation and commit.

## Out of Scope

- M3 or M4 route implementation.
- A permanent tab navigator.
- A local or mocked Ally database.
- A memory editor.
- A manual responsibility editor.
- A routine authoring form.
- A permissions console.
- Multiple conversations for one Ally.
- Runtime administration, token dashboards, or an Ally swarm view.
- Direct Interface calls to Foundry, Hermes, or runtime hosts.
- Invented SSE or WebSocket behavior.
- File attachments until Cloud publishes an accepted attachment contract.
- New analytics, feature flags, navigation frameworks, or state libraries.

## Constraints

- Cloud is the product source of truth.
- The refreshed contract is pinned at SHA-256 `1fceace350f418f1371451356e4dcf5626259cf2148b36d2611c36dfb0ea3b4f`. The live Cloud contract has no collection read for Allies. The workspace must not claim that it lists all server-side Allies.
- Do not persist a fake Ally catalog. Keep only an in-memory set of Ally IDs created or opened during the signed-in app lifecycle. Fetch every displayed Ally from Cloud by ID. Show 12 at a time to bound concurrent reads; Load more reveals the next 12.
- The collection limitation survives app restart. Show an honest empty state and document the limitation until Cloud adds `GET /api/v1/workspaces/{workspace_id}/allies`.
- Reuse the existing `@tanstack/react-query`, Expo Router, Expo Crypto, session adapter, onboarding components, character assets, typography, and motion utilities.
- Do not add a dependency.
- Do not reduce the existing 4,000-character preview reply limit to fit SecureStore. Use the installed Expo Crypto and FileSystem APIs so valid input remains valid.
- Use Open Runde, white space, black type, `#F3F3F3` surfaces, pill controls, `#FF5800` brand orange, and Ally-selected accents.
- Respect reduced motion and native safe areas.
- Use ADS-STE100 Simplified Technical English for technical documents.

## Current Cloud Contract

| Capability | Contract | Status |
| --- | --- | --- |
| Begin onboarding | `POST /api/v1/onboarding/attempts` | Available; sends final name, job, personality, and appearance |
| Create Ally | `POST /api/v1/workspaces/{workspace_id}/allies` | Available; requires `Idempotency-Key` |
| Read Ally | `GET /api/v1/workspaces/{workspace_id}/allies/{ally_id}` | Available |
| List Allies | `GET /api/v1/workspaces/{workspace_id}/allies` | Missing |
| Read by Ally | `GET /api/v1/workspaces/{workspace_id}/allies/{ally_id}/conversation` | Available; cursor pagination |
| Read by conversation | `GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}` | Available; cursor pagination |
| Send message | `POST /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages` | Available; requires `Idempotency-Key` |
| Read activity snapshot | `GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/activities` | Available; bounded `limit` |

## Acceptance Criteria

1. A signed-out user can complete the Ally preview, sign in, and resume the same pending creation command.
2. A signed-in user can also start the existing onboarding flow from the workspace.
3. The final onboarding action sends one validated Cloud creation request with one stable idempotency key.
4. The app renders provisioning, retryable failure, and ready states from the Cloud Ally response.
5. An Ally created in the current app session appears in the workspace only after a successful Cloud response.
6. Opening an Ally fetches its real Cloud record and continuous conversation.
7. Message history uses Cloud ordering and cursor pagination without local fabricated messages.
8. A user can submit a message with one stable idempotency key. Later valid messages remain allowed after each acceptance so Cloud can queue them. A retry reuses the original key and body.
9. A pending create or message command is stored before transport. An unknown result remains recoverable with the same key and body after remount or restart. A create command expires after seven days, binds to the first authenticated user and workspace, and cannot cross accounts.
10. The conversation polls only for known active states, stops after ten minutes or on a terminal, paused, unknown, blurred, or unmounted state, and leaves manual Refresh.
11. Activity rows render only `ActivityResponse.text`; the Interface does not render activity payloads, internal IDs, or runtime fields.
12. The identity screen shows the Cloud name, job, personality, and appearance as read-only data.
13. Account remains reachable and sign-out clears signed-in query and in-memory Ally navigation state.
14. Loading, empty, offline, error, and retry states are visible and accessible.
15. Reduced-motion users do not receive non-essential repeated motion.
16. M3 and M4 screens are documented but are not present as non-working routes.
17. The required repository checks pass.

## Dependencies

- Accepted staging Cloud paths listed above.
- Existing native Google sign-in and session refresh work.
- Existing onboarding visuals and form validation.
- Cloud must add an Ally collection read before the workspace can restore or enumerate all Allies across app restarts and devices.

## Risks

- **Missing collection read:** The workspace can show only Cloud records that it can address in the current app lifecycle. Mitigation: call this an M2 mobile slice, record the exception in Nabu, keep no fake catalog, and replace the in-memory index when Cloud adds the endpoint.
- **Unknown string states:** The OpenAPI uses strings for lifecycle fields. Mitigation: map known product states and render an honest neutral fallback for unknown values.
- **Duplicate creation or send:** A retry can repeat a mutation. Mitigation: encrypt one UUID and exact body to the app document directory before transport; retain them after an unknown outcome and delete them after a definitive result, explicit cancel, expiry, account mismatch, or explicit sign-out.
- **Excess polling:** Background polling can waste battery and data. Mitigation: poll every three seconds only for known active work, stop after ten minutes, and stop on paused, terminal, unknown, blurred, or unmounted state.
- **Stale session:** Authenticated calls can return unauthorized. Mitigation: route every call through the existing refresh adapter and clear the session on terminal authorization failure.

## Implementation Phases

1. Refresh the Cloud contract and add the smallest validated client surface.
2. Add the explicit route/status matrix and the honest workspace.
3. Connect the official preview-first onboarding and OAuth handoff to Cloud creation.
4. Add the continuous conversation and lifecycle polling.
5. Add the read-only identity summary.
6. Validate, review, document, classify the release, commit, and open a PR to `dev`.
