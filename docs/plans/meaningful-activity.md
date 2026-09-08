# Meaningful activity presentation

**Route:** fast

**HTML required:** no

**Delivery:** coordinated Foundry, Cloud, and web Interface PRs into `dev`

## Outcome and scope

Replace the generic activity presentation with privacy-safe, meaningful labels and one visible history row per logical Hermes tool call. The current activity becomes the response headline; completed history remains attached to its response, collapsed and quiet. Preserve the existing Foundry event stream, Cloud receipts/projection, replay cursors, authorization, bounds, stop/retry behavior, and one-conversation-per-Ally rules.

This work does not add a second event system, expose tool arguments/results/queries/URLs/paths, add an approval/resume control, change durable execution semantics, or update mobile. Figma node `315:3255` owns layout geometry: 36px Ally, 14px labels, 18px history icons, 6px icon-to-label gap, 12px row gap, and 14px headline-to-history gap. Use the approved 150ms label and 180ms disclosure transitions, disabled under reduced motion.

## Cross-layer contract

Keep `activity.started` and `activity.completed` in the current `v1` event envelope. Cloud must first accept the explicit legacy-or-rich payload union; Foundry then starts producing rich forms. Unknown keys and invalid values still fail closed.

| Event | Legacy payload retained | Rich payload produced after rollout |
| --- | --- | --- |
| `activity.started` | `{ "kind": "tool" }` | `{ "activity_id": "activity-<32 lowercase hex>", "activity_kind": <allowlist> }` |
| `activity.completed` | `{ "status": "completed" }` | `{ "activity_id": "activity-<32 lowercase hex>", "activity_kind": <allowlist>, "status": "completed" | "failed" | "stopped", "duration_ms"?: 0..86400000 }` |

Legacy and rich shapes are mutually exclusive exact schemas: reject partial rich payloads, legacy/rich hybrids, and extra keys. When present, `duration_ms` is a strict non-boolean integer from 0 through 86,400,000; omission is valid when Hermes supplies no trustworthy duration.

- The pinned Hermes patch uses one correlated `tool_progress_callback` lifecycle path. Every supported serial and parallel start passes `tool_call_id` with the tool name; every real completion passes that same ID plus bounded duration and `is_error`. The API seam forwards this callback metadata into exactly one `tool.started` or `tool.completed` SSE event and does not try to correlate the separate start/complete callback channels by name, order, or timing. It never forwards args, preview, result, query, URL, path, exception, or secret fields. Use a focused pinned-source image patch and image smoke test rather than modifying the external Hermes checkout.
- `allies-runtime` hashes `run_id + tool_call_id` into `activity_id`, keys active calls by that ID, and completes that exact ID. It must not match by tool name. Missing, duplicate, unknown, or contradictory IDs fail closed. A real tool error emits `failed`. Runtime death, fencing, budget exhaustion, interruption, or blocking must not synthesize one completion event per open call; the authoritative execution terminal remains the only guaranteed terminal evidence for those paths.
- During the image transition, Foundry serializes an old runtime activity payload that lacks the new correlated fields back into the exact legacy wire shape. It must not fabricate an ID, kind, duration, or terminal result. This keeps old Machines compatible while new immutable images roll out.
- `activity_kind` is a runtime-owned privacy allowlist. Normalize aliases into: `web_search`, `web_extract`, `browser_navigate`, `browser_interact`, `search_files`, `read_file`, `write_file`, `patch`, `terminal`, `execute_code`, `image_generate`, `video_generate`, `text_to_speech`, `vision_analyze`, `session_search`, `memory_remember`, `memory_recall`, `memory`, `skills_list`, `skill_view`, `skill_manage`, `todo`, `cronjob`, `delegate_task`, or `unknown`. Any unrecognized tool becomes `unknown`; raw tool names never cross into Cloud.
- Cloud keeps the existing append-only `Activity` rows and immutable `FoundryEventReceipt` for replay and audit; it does not add a logical-call table. Add the same nullable safe `activity_id`, `activity_kind`, and `outcome` metadata to both models (plus `duration_ms` on visible `Activity`) and project each rich start/completion event at its existing product sequence when bounds permit. For every public activity event, derive `activity_attempt_id = "attempt-" + sha256("allies:activity-attempt:v1:" + private_attempt_uuid)[:32]`; this Cloud-owned presentation identifier is non-authoritative, requires no DB field, and prevents the private Foundry attempt UUID from entering public JSON. The public activity response adds nullable `activity_attempt_id`, `activity_id`, `activity_kind`, `outcome`, and `duration_ms`; legacy API payloads without them remain valid and generic.
- Interface folds events by `message_id + conversation_turn_ordinal + activity_attempt_id + activity_id`. The lowest start sequence fixes display order. The first valid terminal for that exact identity wins: exact repeats are idempotent, while a later conflicting terminal or post-terminal start cannot rewrite or reopen it. Cloud enforces this under its existing projection transaction by querying immutable receipts for prior lifecycle state, never only the possibly suppressed `Activity` rows. It records a valid event receipt even when product bounds suppress the visible row, and records a later contradiction with no product `Activity`/product sequence, so attempt sequence continuity and replay remain gap-free. Interface repeats the same monotonic rule defensively. When an `execution.failed` or `execution.stopped` event arrives, open calls with that exact public attempt identity derive the corresponding failed or stopped display without creating extra lifecycle events; real completed calls remain completed. An execution success with an unclosed call becomes a static safe “Activity status unavailable” presentation rather than false success. Missing attempt/activity identity uses the honest legacy fallback and never closes a call across an unknown attempt boundary.

Cloud owns the user-visible text; Interface owns layout, motion, disclosure, and icon selection. Use these active/completed labels, with failed copy `Could not finish <active phrase>` and stopped copy `Stopped while <active phrase>` so terminal failures never receive success wording:

| Kind(s) | Active | Completed |
| --- | --- | --- |
| `web_search` | Searching the web | Searched the web |
| `web_extract` | Reading a webpage | Read a webpage |
| `browser_navigate` | Visiting a webpage | Visited a webpage |
| `browser_interact` | Interacting with a webpage | Interacted with a webpage |
| `search_files` | Searching files | Searched files |
| `read_file` | Reading a file | Read a file |
| `write_file` | Writing a file | Wrote a file |
| `patch` | Editing a file | Edited a file |
| `terminal`, `execute_code` | Working | Finished an activity |
| `image_generate` / `video_generate` / `text_to_speech` | Creating an image / video / audio | Created an image / video / audio |
| `vision_analyze` | Reviewing an image | Reviewed an image |
| `session_search` | Searching conversation history | Searched conversation history |
| `memory_remember` / `memory_recall` / `memory` | Remembering / Recalling / Working with memory | Remembered / Recalled / Finished working with memory |
| `skills_list`, `skill_view` | Checking skills | Checked skills |
| `skill_manage` | Updating skills | Updated skills |
| `todo` | Updating the work plan | Updated the work plan |
| `cronjob` | Working with routines | Finished working with routines |
| `delegate_task` | Coordinating delegated work | Finished delegated work |
| `unknown` | Working | Finished an activity |

`write_file` must remain “Wrote a file”; “Created” is allowed only if a later trusted, typed outcome proves creation. Duration is optional bounded detail. No raw detail text is added.

## Implementation sequence

1. **Cloud compatibility and projection.** Extend both copies of the strict Foundry event validator to accept the exact legacy-or-rich activity union, add nullable safe lifecycle metadata to `FoundryEventReceipt` and `Activity` through a migration, project meaningful safe text, expose the additive optional API fields with hashed `activity_attempt_id`, and add contract/projection tests for strict allowlists, identity, receipt-backed first-terminal-wins conflicts, product suppression, outcomes, bounds, legacy rows, replay continuity, stale events, tenant isolation, and absence of the private attempt UUID from public JSON.
2. **Foundry and pinned Hermes seam.** Add the focused Hermes image patch and smoke test. Update every supported serial and parallel executor branch to send `tool_call_id` on start and the same ID plus duration/`is_error` on real completion through the single progress callback. Have the API seam translate that path into exactly one SSE lifecycle event, then replace name-based matching in `runtime/allies_runtime/hermes.py` with ID-based tracking, normalize the activity allowlist, and preserve the current bounded event budgets. Do not manufacture per-call completion events for blocked/interrupted execution terminals. Update Foundry wire validation/serialization to emit the rich payloads and test concurrent same-name calls completing out of order, tool errors, blocked/interrupted terminals, unknown kinds, malformed IDs, duplicate/stale completion, exactly-once SSE emission, and privacy exclusions.
3. **Web projection and presentation.** Generate OpenAPI locally with the checked-out Cloud repository's existing generator, record the exact Cloud commit SHA and SHA-256 of the produced schema, and regenerate the Interface client from that same file; provenance must say local branch artifact and must not claim deployed staging. Fold lifecycle events into stable logical rows with defensive first-terminal-wins behavior, select the newest ongoing call for the headline, and render completed/failed/stopped history collapsed beside its response. Only an ongoing header shimmers; history rows never shimmer or glow. Apply Figma geometry and approved motion with reduced-motion behavior. Keep `Thinking` when work is active but no rich ongoing activity exists.
4. **Temporary icon layer.** Add the MIT-licensed `iconsax-reactjs` package and lockfile change. Use Iconsax **Bulk** icons through one centralized `activity_kind -> icon` map; components consume only that map. Record package/version/license in the PR. This is a replaceable temporary asset layer and must not leak icon-library names into transport or product contracts.
5. **Integrated proof and delivery.** Run focused and repository checks at each current branch head, then separate correctness and simplicity review, secret scan, CI, and Enkii for all three PRs. Keep PRs independent where possible and cross-link the required rollout order.

## Acceptance and validation

- Two concurrent calls with the same normalized kind complete out of order and update only their own logical rows.
- Exact duplicate/replayed events are idempotent. The first valid terminal wins even when its product row was suppressed: a hidden failed terminal followed by a shorter otherwise-visible success still retains the failed receipt truth, creates no success activity, cannot regress/reopen the row, and does not break receipt or replay sequence continuity.
- Completed, failed, stopped, blocked/interrupted, unknown, and legacy activities remain truthful. Open rows derive failed/stopped state only from a terminal event with the same attempt identity; a successful execution with a missing call completion is shown as unavailable, never completed. Failed rows never use completed wording; quiet completed history survives reload/reconnect and remains attached to its response.
- Only the latest ongoing activity replaces `Thinking`; only its header shimmers. Rows remain static, disclosure is keyboard/screen-reader usable, and reduced motion disables label/disclosure animation.
- Existing receipts, cursor replay, retention and payload limits, safe allowlists, terminal execution truth, and public authorization continue to pass.
- Contract fixtures reject hybrid/partial rich payloads, extra keys, boolean/fractional/negative/oversized durations, and accept a rich completion with duration omitted.
- Generated Cloud client evidence names the local Cloud commit and matches the recorded schema SHA-256; it makes no staging-deployment claim.

Run at minimum:

```text
# Foundry
cd runtime && uv run --locked pytest tests/test_hermes.py -q
cd .. && make test APP=runtime
make check && make validate && make lint

# Cloud
make test APP=activities
make check && make lint

# Interface
bun run test:run apps/web/lib/allies/activity-presentation.test.ts apps/web/app/home/home-workspace.test.tsx
bun run cloud:check
bun run lint:web && bun run typecheck && bun run build:web
```

Add an image smoke that exercises the real patched Hermes SSE with two same-name calls, IDs, error status, and privacy exclusions. Before handoff, verify current-head hosted CI, secret scan, and Enkii on every PR; a prior run or an earlier commit does not satisfy the gate.

## Rollout, rollback, and risks

Deploy Cloud compatibility first. Merge/deploy Foundry next, publish tested immutable Hermes and Allies runtime image digests from the Foundry head, update staging image configuration, and replace or reconcile a test Fly Machine because existing Machines retain old images. Deploy Interface after rich Cloud activity is observable. Old runtime events continue to render through the legacy fallback.

Rollback in reverse: Interface first, then Allies runtime/Hermes image configuration, then Foundry. Leave the nullable Cloud schema and dual reader in place until no rich producer remains; rolling Cloud code back while rich Foundry events are live would reject valid traffic. No production promotion, merge, or direct push is authorized.

Material risks are contract drift between the duplicated Foundry/Cloud validators, losing completion updates during replay, and accidentally exposing Hermes details. Paired fixtures, append-only sequences/receipts, strict safe payloads, and image-level SSE proof mitigate them. Iconsax Bulk is temporary; the centralized map contains the replacement cost. The exact icon-to-kind choices may be adjusted during implementation without changing contracts, copy, layout, or behavior.
