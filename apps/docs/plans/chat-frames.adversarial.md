# Adversarial Review

## Verdict

Needs revision

## Findings

| Severity | Area | Finding | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| Major | Activity correctness | The proposed flat activity log does not define grouping by message and turn. A latest-turn group can misattribute retained events after multiple or interrupted turns. | Plan sections on activity presentation and the existing Cloud activity mapper | Define a turn-scoped presentation structure keyed by `messageId` and `conversationTurnOrdinal`, place it after the triggering user message, and test multiple turns, replayed/out-of-order events, conversation changes, and cap eviction. |
| Major | Fixture isolation | A combined production-plus-synthetic union leaves rich rendering branches inside the production conversation component; TypeScript types alone do not enforce the debug-only boundary. | Plan contract, scope, and fixture-isolation sections | Limit the production renderer to `ProductionConversationFrameModel`; keep rich branches/actions in a debug-only wrapper/module while sharing visual primitives. Add static import-boundary tests for production and debug modules. |
| Major | Visual proof | Fidelity depends on an unpinned Aphrodite alias and unidentified manual approval. No durable per-frame measurement/asset manifest or design revision/sign-off link is retained. | Plan evidence, visual acceptance, and open-question sections | Pin the design revision/export checksum, record a complete 25-frame measurement/content/asset manifest, name the approving owner, and create a durable baseline sign-off record linking every capture to its source node/revision. |
| Major | Regression enforcement | The Playwright visual suite is manually invoked, not a package script or required CI job, so approved snapshots can regress without a required check. | Plan browser-validation sections; existing CI and web package scripts | Add a stable chat-frame script and required CI job with pinned browser/runtime versions and uploaded snapshot/diff artifacts, or define an enforceable pre-merge evidence gate and owner. |
| Major | Permissions and authorization | The plan lacks explicit permission-denied behavior for conversation load, send, retry, and activity access even though the client distinguishes forbidden responses. | Plan state/test sections; Cloud error types; engineering policy | Define 401, 403, and inaccessible/not-found behavior for each production request surface, including preservation and recovery rules, and test that forbidden responses do not expose stale cross-scope data or offer ineffective retries. |
| Question | Debug-route exposure | Enabling `/chat-frames` in preview/staging may publicly expose synthetic handoff content and extracted assets. | Plan debug-route and environment-guard sections | Resolve whether public preview/staging exposure is acceptable. If not, require authenticated or secret access and test development, preview, staging, and production behavior. |
| Minor | Responsive and cross-browser validation | Non-reference checks are broad smoke statements; WebKit/Safari support and 200% zoom have no executable projects or pass/fail criteria. | Plan responsive and manual-validation sections | Name supported engines and exact Playwright projects/versions, define reflow/clip/focus/composer-overlap assertions at each viewport and 200% zoom, and distinguish WebKit from actual Safari validation. |

## Disposition

All findings are accepted for planning revision. The preview/staging exposure item and the named baseline approver remain owner decisions; the revised plan must make the default safe behavior explicit if no owner decision is available. No application code was changed during this review.

## Plan Feedback For Revision

- Replace flat activity presentation with message/turn-scoped grouping and ordering.
- Enforce the synthetic rich-state boundary structurally through module ownership and import tests.
- Add immutable design evidence, complete frame manifest, named approval/sign-off, and calibrated visual-diff policy.
- Make visual validation executable through scripts/CI or an explicit owned pre-merge gate.
- Add permission-specific production states and tests.
- Resolve or safely guard preview/staging debug-route exposure.
- Turn responsive, zoom, and cross-browser checks into measurable browser assertions.

## Second adversarial review

### Verdict

Needs revision

### Findings

| Severity | Area | Finding | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| Major | Baseline lifecycle | Baseline generation runs the sign-off verifier even though the unsigned approver sentinel and capture hashes are intentionally invalid, creating a circular path where initial captures cannot be generated for review. | Revised plan baseline/sign-off section and the `test:chat-frames:update` command. | Split pre-baseline manifest/runtime verification from post-baseline sign-off verification. The update command may create provisional unsigned captures; CI/merge must require completed sign-off. |

PR #22 disposition: the circular update path remains split, but the final merge requirement above is superseded by the explicit, time-bounded D-04 exception in `chat-frames.md`. The repository maintainer accepts the deterministic pinned-Linux captures provisionally; product/design provenance is due before the first production release or any intentional baseline update, whichever comes first.
| Major | CI trigger/branch | The plan requires a `Chat frame regression gate` but does not state which PR target receives it; current CI triggers only for `dev`, `staging`, `prod`, and `prod-fastlane`, while this work is based on `web/dev/figma-chat-ui`. | Revised plan branch/base evidence and `.github/workflows/ci.yml` pull-request branches. | Name the intended PR target. If the feature PR targets `web/dev/figma-chat-ui`, extend the workflow trigger; otherwise state that it targets an existing covered branch and preserve the required status there. |
| Major | Boundary enforcement | The proposed source-graph test follows relative static imports, but the acceptance claim is broader and does not cover aliases, re-exports/barrels, dynamic imports, or CommonJS escape paths. | Revised plan static-boundary section. | Define exhaustive resolver coverage for imports/exports, aliases, dynamic imports, and CommonJS, or narrow the claim and add a production bundle-graph assertion excluding debug modules/assets. |
| Major | Asset evidence | Symbolic `existing-ally-art`/`native-icon` labels plus one raster do not prove every material Aphrodite asset is reproduced or intentionally substituted; asset diagnostics were compacted/truncated. | Revised plan manifest section and Aphrodite extraction notes. | Require each frame manifest asset to map to an exact tracked asset, verified reusable asset, masked OS chrome, or documented native/CSS substitution with approver acceptance. Resolve and record complete asset evidence before calling the manifest complete. |
| Minor | CI artifact failure | `actions/upload-artifact@v4` warns when expected files are absent by default, so the stated missing-artifact failure is not executable. | Revised plan CI section and GitHub action behavior. | Add `if-no-files-found: error` and validate expected report/diff paths before upload. |

### Missing questions

- Which branch will receive the implementation PR and the required visual status?
- Who is the baseline approver, and where will Safari/actual-zoom evidence be recorded?

### Disposition

All findings are accepted for planning revision. No application code changed during this review. Implementation remains blocked until the revised plan and Lavish HTML address these findings and pass a fresh simplicity review.

## Simplicity review

### Verdict

Needs revision

### Findings

| Severity | Area | Finding | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| Major | Baseline lifecycle | Requiring a CI-run URL in the sign-off record makes sign-off depend on the post-sign-off CI run. | Plan lines 45, 54–55, 485–486, 521–523 before this revision. | Permit the URL to be absent/null during sign-off verification and attach the successful run URL afterward as PR/release evidence. |
| Major | CI artifacts | Actual/diff images and traces are failure-dependent, but the plan required them on every upload. | Plan lines 486 and 526 before this revision. | Always require report/results/summary and baseline expected images in one artifact; include Playwright-managed traces/actual/diffs within the results directory when they exist, without a separate retry-sensitive marker. |
| Minor | Asset evidence | The 25-row prose ledger repeats the same provisional invariant and can drift from the machine-readable manifest. | Plan lines 57–89 before this revision. | Make the JSON manifest the single asset ledger; retain only the exact 25-ID and per-asset completeness rule in prose. |
| Major | Browser matrix | Running the full viewport and interaction matrix in all three engines is more work than needed for this pixel-baseline slice. | Plan lines 481–484 before this revision. | Keep full pixel/layout/interaction coverage in Chromium; run representative minimum-width, desktop, 200%-reflow, keyboard/focus, overlay, and auth/error behavior checks in Firefox/WebKit, with actual Safari/200% zoom manual evidence. |

### Disposition

All four findings were routed through planning. The revised plan removes the circular CI prerequisite, makes failure-only artifacts conditional, makes the manifest the sole asset ledger, and narrows Firefox/WebKit to representative behavior coverage while retaining full Chromium raster/layout coverage. No application code changed during this review.

## Final adversarial verification

### Verdict

Pass

### Verification

The final bounded review confirmed that the CI-target disposition references `D-10`, the Lavish source SHA-256 and byte-length metadata match the current Markdown, and the plan retains the no-pre-signoff-CI-URL rule, conditional failure-only artifact rule, manifest-only asset ledger, and representative Firefox/WebKit behavior scope. No application code changed.
