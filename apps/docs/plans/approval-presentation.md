# Approval presentation repair

Status: Ready for implementation review. Route: **FAST**. HTML required: **no**; recorded Aphrodite evidence and browser verification cover visual review. Branch `web/fix/approval-presentation`, base `dev`. Deliver one focused PR to `dev`; do not merge.

## Outcome and scope

Show Cloud's request-bound plain-language explanation first, with complete safe technical details closed initially. Match the recorded approval design on mobile and desktop. Replace the Previous approvals button group with clickable activity-style history rows opening read-only details. Verify production summary generation prerequisites separately from the Interface change.

Cloud remains the owner of explanations, authorization, expiry and durable decisions. No browser model calls, new provider integration, Foundry calls, authority changes, new dependencies or native-mobile presentation changes. The shared client remains compatible with mobile.

## Evidence and current mismatch

- Read root `AGENTS.md`, `ENGINEERING_STYLE.md`, `apps/web/AGENTS.md`, `README.md`, root/web package scripts, `vitest.config.ts`, `.github/workflows/ci.yml`, and `apps/web/playwright.chat-frames.config.ts`.
- Nabu index, `projects/allies/engineering/specs/conversation-and-streaming.md` (revision `abf7872afb181406f8651dd0e4ee8944460ca33cd3ad90ea4bb93a883ce242fb`) and `projects/allies/delivery/alpha-test-tracker.md` establish the accepted explanation/disclosure contract and unverified AT-028 rollout. AT-030 still says history needs a decision; the user's latest explicit activity-row decision supersedes that entry. The orchestrator should reconcile the canonical tracker using revision-aware writes.
- `packages/cloud-client/src/mappers/approvals.ts` currently drops explanation/binding fields; `client.ts` already rejects responses for another approval resource ID. `conversation-approvals.tsx` renders `actionPreview` in the default view, groups terminal requests under Previous approvals, and scopes accent to rows rather than the sibling dialog.
- Inspected approval mapper/client tests, approval UI tests, `activity-icon.tsx`, `conversation-frame-primitives.tsx`, `conversation-frame.module.css`, and activity presentation. Existing tests protect duplicate taps, uncertain retries, focus restoration, message placement, access removal and deadlines. Reuse these safeguards.
- Cloud `origin/prod:backend/activities/api/schemas.py` and `services/approval_explanations.py` expose `approval.v1` / `approval-explanation.v1`, request UUID, preview digest, four bounded text fields, source, and safe technical details. Generation uses fixed `gpt-5.6-luna`, a default-off flag, shared-cache budgets and a persisted single attempt. The generated Interface OpenAPI file already references this explanation contract; check the pin before proposing any snapshot update.
- Design evidence is inherited from the inspected episode: Aphrodite frame `355:6222`, sheet `355:6317`. Mobile baseline 351×233, radius 30, horizontal padding 20, yellow approval/check badge, circular 36px close button, centered 24px Open Runde semibold question, two 150×48 pill actions with 12px gap. Summary/disclosure increase height naturally; desktop centering is accepted.

## Implementation steps and contracts

1. **Map the existing public explanation safely.** Extend `packages/cloud-client/src/mappers/approvals.ts` and its tests. Keep the existing base detail validation strict and unchanged. Parse the optional presentation extension—including the envelope request UUID, envelope preview digest and explanation—separately from that base. Missing, malformed or partial extension fields drop the explanation only; they never invalidate a valid GET detail or durable decision receipt. Only a complete, valid envelope UUID/digest pair permits bound explanation validation. Legacy responses always use the fixed UI fallback. Accept only `approval-explanation.v1`, UUID binding, `sha256:` plus 64 lowercase hex characters, `model|fallback`, and all four nonempty text fields (`action`, `target`, `consequence`, `reason`) bounded to 240 Unicode characters without control characters. Compare explanation `approval_request_id` to the detail's `approval_request_id` (not the public approval `id`) and explanation digest to the detail's `preview_digest`. These are the authoritative Cloud binding fields; do not invent a client digest format or a second authority. Validate `technical_details` against the allowlisted kinds (`terminal`, `execute_code`, `plugin_tool`), existing label/preview limits, and consistency with the top-level safe preview. Discard malformed optional technical metadata and retain the validated top-level safe preview. Keep existing fields and exports compatible. Do not loosen response-resource ID checks for GET or decision receipts.

2. **Render summary and disclosure without changing decisions.** Update `apps/web/app/home/conversation-approvals.tsx`. Render all four accepted fields as plain text, never Markdown/HTML or executable links. If presentation is absent/invalid/unbound, use fixed honest copy describing the request and directing the user to details; never derive default copy from raw code, arguments or `actionLabel`. A native details/summary control labelled **View technical details** starts closed for each opened request and reveals the full validated safe preview plus available validated action kind/label. Never truncate the authorized preview. Keep loading, load failure/retry, read-only permission, pending, recording, uncertain decision, acknowledgement and terminal states explicit. Preserve close/Escape dismissal, request-keyed intent, same-choice/key retries, double-tap prevention, expiry checks, terminal precedence and close-after-durable-receipt behavior.

3. **Apply the recorded design locally.** Use approval-scoped rules in `conversation-frame.module.css`; pass the Ally accent onto the dialog's own scope, using a narrow optional style/header slot on `BottomSheet` only if needed. Add the approval/check badge and use an approval-specific status icon instead of the unknown/wand icon for approval rows. Keep unrelated activity icons and sheets unchanged. Match the mobile measurements above, short centered question, neutral Reject/accent Approve pill actions and circular close control. Allow content growth and vertical scrolling within the viewport, including long summaries/previews and narrow screens. Preserve native modal focus containment, accessible name, visible focus, keyboard disclosure and focus return.

4. **Make history a clickable activity row.** Within the existing per-message/fallback approval slots, replace terminal button grouping with semantic buttons styled like `frameActivityEntry` (icon, status text, optional existing timestamp). Reuse activity tokens, not a second history store or feed. Rows remain discoverable without expanding Previous approvals, keyboard operable, and uniquely keyed by approval ID. Terminal and decision-recorded rows reopen read-only details with no Approve/Reject actions; dismissed pending requests remain reopenable. Preserve exactly-once placement when messages move from active to historical/fallback slots, and return focus to the triggering row. Adjust the existing terminal-focus test to the new structure. If existing generic activity entries also represent approval requests, inspect their approval identity before rendering and avoid adding a duplicate approval interaction.

5. **Verify configuration and delivery evidence.** The parent orchestrator owns Railway diagnosis and any authorized corrections. Record effective `ALLIES_APPROVAL_SUMMARIES_ENABLED`, presence-only `ALLIES_WAITLIST_OPENAI_API_KEY`, usable `CACHE_URL`, configured budgets and compatible Foundry provenance/action kind. Never print values or persist commands/previews/customer credentials. Flag presence is not successful generation: use a fresh benign pending approval, because existing persisted fallbacks are not regenerated by toggling the flag. Verify the returned source/bindings and safe technical disclosure; retain fallback on provider/budget failure. Do not clear persisted claims, relax budgets, replay a historical credential-bearing request or weaken continuation gates to obtain proof. Record configuration-only evidence honestly if a fresh generation test is unavailable. Reconcile AT-028/AT-030 evidence in Nabu without claiming rollout or same-invocation continuation was tested when it was not.

### Production enablement prerequisite

Parent diagnosis found the summary flag in Railway production shared variables but absent from the Backend's resolved variables. A synthetic test of the existing Foundry producer image also showed that forced redaction retained a capability token embedded in a URL path. **Do not wire/enable model summaries until the parent repairs the producer and proves safe redaction before external transmission using synthetic fixtures.** The parent owns that narrow Foundry repair and synthetic model smoke independently. Frontend implementation can proceed; this prerequisite does not expand its design or permit displaying/externalizing unsafe previews. Record producer/deployment proof separately from flag configuration and model-generation proof.

## Acceptance and focused tests

- Mapper tests: model and Cloud fallback sources; missing/partial/invalid fields; unsupported version/source; request UUID mismatch; digest mismatch; technical-preview mismatch; Unicode bounds and oversized/NUL previews. Invalid optional copy never appears and never changes a valid 200/202 decision receipt into a failed decision. Explicitly cover GET details and both 200/202 decision receipts for legacy, complete and partial extensions: legacy/partial responses retain valid base details and use fixed UI fallback; complete responses show an explanation only when its binding validates. Keep malformed-base and wrong-resource-ID rejection tests.
- UI tests: summary visible while technical content is initially hidden; disclosure opens full preview; invalid/missing summary yields fixed plain copy; request switch/reopen closes disclosure; history rows open read-only detail and restore focus; pending reopen still works; message/fallback placement remains unique. Retain the existing uncertain-response/idempotency, duplicate-tap, access, expiry and terminal-status tests with both generated and fallback presentation.
- Render the actual `ConversationApprovals` flow with synthetic API fixtures, not only the separate static `ApprovalSheet` catalog. Browser checks at 375×812 and a desktop viewport, light/dark, at least two Ally accents, and a narrower viewport confirm badge/close sizing, centered heading, 48px pill actions, spacing, summary/disclosure hierarchy, scrolling, visible focus and terminal history interaction. Verify Escape, Tab containment and focus return; compare screenshots against the recorded Figma measurements. Keep fixtures free of real secrets.

## Validation commands

Run from the worktree root with locked Bun 1.2.20. These are planned checks, not executed results.

```powershell
bun install --frozen-lockfile
bun run test:run --project=packages packages/cloud-client/test/approvals.test.ts
bun run test:run --project=web apps/web/app/home/conversation-approvals.test.tsx
bun run cloud:check
bun run typecheck
bun run test:run
bun run lint
bun run build:web
bun run --cwd apps/web test:home-smoke
bun run test:chat-frames --project=chat-chromium
bun run bundle:mobile
git diff --check
```

The shared mapper justifies workspace type/tests and mobile bundle validation. Follow CI's browser scope if changed primitives require the full `bun run test:chat-frames` matrix; run `bun run --cwd apps/web test:ally-motion` only if the change actually affects motion scope. Do not update unrelated screenshot baselines to hide regressions. Use the Home smoke harness with the production build for the real approval flow; use the existing dev-server harness for shared frame regression checks. Add the focused browser regression to the existing Home smoke harness where practical; keep demo-only code outside production bundles.

## Risks, rollback and open items

- Main risks are losing a durable decision because optional copy fails validation, exposing technical content by default, duplicate history rows, and changing shared sheet behavior. Separate optional presentation validation, retain decision tests, scope CSS and exercise the actual flow.
- Legacy or incompatible Cloud details must produce fixed fallback; lack of model copy must not block safe approval or imply generation succeeded. Shared-client changes must not break native consumers.
- Revert the focused Interface change to roll back presentation; this does not revert recorded approvals. If configuration correction is unhealthy, restore the previously recorded flag value while preserving all approval records and safety gates.
- No unresolved product decision blocks implementation. The remaining operational question is whether effective production settings and fresh provenance permit model generation; the parent supplies that result. No HTML artifact or further confirmation is needed for the settled scope.
- Keep this as one coherent PR, targeting roughly 200–500 changed lines excluding generated files. Reassess independent refactors if it grows; retain relevant tests. Require separate simplicity and correctness/policy reviews plus existing CI/security checks before the PR handoff. Retain the worktree while awaiting merge.
