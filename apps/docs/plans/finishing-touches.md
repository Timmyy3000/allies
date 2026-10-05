# Finishing touches

## Feature overview

- **Problem:** Normal pull requests currently run the full Interface matrix even when a change cannot affect web builds, browser behavior, or mobile export. The chat-frame browser suite also records video and exercises fixture-only rich actions, while the desktop Exact shell depends on seven externally hosted runtime SVGs.
- **Outcome:** Keep the invariant contract, type, unit, lint, security, release, and full-suite gates; run platform and browser work according to a conservative changed-path contract; replace fixture-only browser work with deterministic smoke coverage of the real Home routes; and serve the seven desktop Exact SVGs locally without changing design.
- **Baseline:** The prior partial CI observation was 4m33s overall with 181s in the browser portion. It is directional evidence only; this plan does not promise a speedup.
- **Delivery:** Branch and PR title `web/ft/finishing-touches`, targeting `dev` from merged PR22 commit `8eef596`. No merge is authorized.

**INT-03 naming exception:** The user explicitly required both the branch and PR title to be `web/ft/finishing-touches`. The repository maintainer owns this exception for PR29 only, including its shared CI changes. A web prefix could understate that scope; the PR description and this plan explicitly disclose repository-wide validation routing, and shared changes still receive full CI. Revisit when this PR closes; future standalone CI work returns to a non-platform prefix. This exception changes no validation or access-control rule.

## Review follow-up — 2026-09-07

The user accepted optional exact screenshot comparisons while the design changes quickly. This supersedes the earlier requirement below to run all raster comparisons in ordinary CI. Normal PR, scheduled, and promotion runs retain browser geometry/overflow/hit-area/interaction checks, Home smoke, motion, types, unit tests, lint, contract and security checks. Manual CI dispatch can select `visual_snapshots` to compare all 25 preserved baselines with the unchanged threshold.

Review fixes preserve unconfirmed server sign-out through a homepage retry screen, keep accepted/unclaimed immediate messages visible, restore the missing mobile fade CSS with a browser assertion, offer account-switch recovery without deleting a saved handoff, and select cross-browser coverage for spec-only changes. The unused post-auth resume path is removed. The Google mark uses a simple vector without blur filters.

## Scope and contracts

Use one dependency-free changed-path classifier, invoked by the workflow after checkout. Do not use workflow-level `paths` filters, because they can prevent the required invariant checks from starting. Missing comparison data, workflow/toolchain changes, shared code, and unrecognized paths select the full suite.

For PRs, execute the classifier retrieved from the trusted base commit, never the PR's copy. If that base has no classifier, run the full suite. Non-PR validation also selects full directly. A classifier edit therefore cannot suppress its own validation.

| Change class | Required pull-request checks |
| --- | --- |
| Every change, including docs-only | Pinned Cloud contract, all workspace types, unit tests, lint, secret scan, and existing policy/security review |
| Web | Invariant checks, web build, real-Home smoke, and Chromium browser coverage |
| Relevant UI, styles, browser config, or all-flags mode | Web checks plus WebKit and Firefox where supported by the affected suite |
| SVG player/motion | Invariant checks plus the Chromium/WebKit Ally-motion suite |
| Mobile | Invariant checks plus iOS export |
| Shared package, toolchain/lock/config, workflow, unknown, or classifier failure | Full web build, browser matrix, and mobile export |
| Weekly schedule, manual dispatch, promotion/release reusable calls | Full suite regardless of changed paths |

Keep the current visual manifest, all 25 approved Chromium raster baselines, pixel-difference threshold, runtime/bundle boundary checks, failure screenshots/traces, artifact retention, least-privilege workflow permissions, Gitleaks, and Enkii behavior. Remove video capture and only the fixture-only synthetic rich-action interaction test; do not delete or replace any signed-off screenshot, or weaken the visual, geometry, accessibility, queue, or SVG-player checks.

The Home smoke must exercise the real `/home`, `/home/<owned-id>`, and `/home/new` page/component graph from a production `next start` server. Playwright HTTP route interception returns deterministic synthetic session, account, roster, conversation, and activity responses. `/home/new` proves the authenticated creation entry renders; this smoke does not submit an Ally creation. Add no separate mock server, production auth bypass, application fixture mode, dependency, or alternate Home component.

Vendor the seven SVGs used by `dashboard-ui-push-exact.tsx` under the existing public Home asset area and change only those runtime `src` values to same-origin paths. Preserve a reviewable source-URL-to-local-path mapping in the diff, all seven raw SVG payloads, the authored dimensions, placement, semantics, and raw Figma reference documents. Validate the downloaded SVGs contain no scripts, event handlers, or unexpected external references. A focused boundary assertion prevents the runtime Exact shell from regaining Cloudinary URLs.

## Implementation phases

1. **Classify changes conservatively.** Add one small repository script using the installed runtime/standard library and focused CLI tests. It reads the base/head diff and emits exactly four flags: `web`, `mobile`, `browsers`, and `motion`. Missing, malformed, unknown, or failed classification sets every flag, which is the full suite. Wire the outputs to step-level conditions in `.github/workflows/ci.yml`; keep invariant steps unconditional and set every flag for weekly, manual, reusable promotion, and release execution.

2. **Right-size browser evidence.** Keep Chromium for ordinary web pull requests. Add WebKit/Firefox when UI, stylesheet, browser-test infrastructure, or all-flags paths change, and run the existing Chromium/WebKit motion suite from the independent `motion` flag. Remove retained video and the synthetic rich-actions behavior case while preserving the complete 25-file signed-off screenshot inventory and geometry suite. Add Playwright HTTP interception and smoke the three real Home entries from a production build/start, including authenticated roster/conversation rendering, creation entry, and the absence of production fixture content.

3. **Make desktop Exact assets self-contained.** Store all seven inspected raw SVG payloads locally, update the Exact runtime shell to their mapped paths, and add the narrow external-asset/security regression. Do not edit layout, copy, colors, motion, artwork, the 25 screenshot baselines, or the generated reference HTML.

4. **Validate behavior and CI routing.** Run focused classifier, asset, Home, and browser tests; then run the unchanged full local contract once. Open the PR with the exact title above, confirm the hosted Railway preview and GitHub checks, and compare job/step timing with the partial 4m33/181s observation without claiming causal improvement from a single run.

## Acceptance criteria

1. Contract verification, workspace typecheck, unit tests, and lint run on every PR. Existing secret, policy, and security checks remain active.
2. Web build/browser and mobile export follow the table above; shared, toolchain, workflow, unknown, and classification-error cases run full. No top-level workflow path filter can strand required checks.
3. Weekly, manual, reusable promotion, and release validation set all four flags and run the complete suite.
4. Chromium covers normal relevant web PRs; WebKit/Firefox cover relevant UI/style/browser changes and every all-flags run; the motion flag retains Chromium/WebKit player coverage. Browser video and the fixture-only rich-actions interaction are gone while all 25 raster baselines and their threshold remain unchanged.
5. Browser smoke reaches the real Home routes through Playwright HTTP interception against production Next build/start. Production authentication, authorization, account scoping, and route code contain no test bypass or mock server.
6. All seven desktop Exact runtime SVGs load from repository-owned paths, pass the SVG safety inspection, and render with no intended visual change. Runtime code contains no Cloudinary reference for them; reference HTML may retain source provenance.
7. Local full validation and hosted PR checks pass. Timing is reported as observed evidence, with no promised speedup. The PR targets `dev`, remains unmerged, and is ready for user review.

## Validation

- Focused: classifier CLI success/error tests; Exact asset-path and SVG-safety checks; Home unit/route tests; Chromium Home smoke; 12 local geometry/browser checks; and 10 local Ally-motion checks.
- Full local: `bun run cloud:check`, `bun run typecheck`, `bun run test:run`, `bun run lint`, `bun run build:web`, `bun run --cwd apps/web verify:chat-frames`, the 12 non-raster geometry/browser checks, `bun run --cwd apps/web test:ally-motion` for the 10 motion checks, and `bun run bundle:mobile`.
- Browser/all-flags mode: run Chromium, WebKit, and Firefox according to the matrix and verify the unchanged manifest, 25-file baseline inventory, diff threshold, bundle boundary, failure artifacts, and no video output. Keep raster comparison on hosted Linux rather than treating Windows rendering as baseline evidence.
- Hosted: confirm Railway preview build and real route rendering; validate all 25 Linux Chromium raster screenshots in CI because the signed baselines are platform-specific; then verify Gitleaks and independent correctness/security review against the exact PR head.

## Risks and rollback

- **False-negative path classification:** default to full, test representative path families and missing/invalid diffs, and keep all invariant checks unconditional.
- **Reduced browser signal:** preserve signed-off visual/geometry/player coverage, use cross-browser escalation for relevant changes, and keep periodic/manual/release full runs.
- **Intercepted-response drift:** intercept only the public Cloud calls already consumed by Home, use synthetic deterministic responses inside Playwright, and keep hosted preview verification as separate evidence.
- **Vendored asset drift or unsafe SVG content:** preserve source-to-local mapping, inspect payloads, and compare the Exact shell in browser without updating baselines.

Rollback is a focused revert of the classifier/workflow conditions, browser smoke/config changes, and local SVG path change. There are no schema, dependency, API, authentication, or user-data migrations.
