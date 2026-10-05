# Managed reasoning defaults

Status: ready for plan review. Route: fast. HTML required: no.
Base: `dev` at `bd8060c`. One focused Foundry change; no product UI changes.

## Outcome and scope

Foundry supplies a centrally managed reasoning effort, initially `xhigh`, for every Allies execution, including existing profiles and resumed sessions. Keep `gpt-5.6-luna` and existing model selection intact. After the compatible runtime is adopted once, changing the Foundry setting and restarting/reloading Foundry processes changes subsequent claims without rebuilding either runtime image or rewriting profiles.

Keep profile settings, explicit local configuration, credentials, skills, memories, sessions, and other persistent state intact. The managed request value intentionally takes precedence for Allies-originated turns; existing profile/session overrides remain stored and continue to govern other callers according to Hermes precedence. This introduces no user preference, override UI, configuration service, database migration, profile rematerialization, or new scheduling. Keep the existing 30-minute keep-warm setting and all shutdown/startup timing unchanged.

## Evidence and decision

- `backend/config/settings.py` defaults `PROFILE_PROVISIONING_MODEL` to Luna. `backend/runtime/services/claims.py::_claim_from_records` takes the model from the immutable profile seed; `backend/runtime/api/register.py::_claim_json` serializes the internal claim.
- `runtime/allies_runtime/foundry.py` parses `FoundryClaim`, creates or resumes the session, then dispatches through `_stream_events`. Both buffered and incremental Hermes clients currently send only `{"message": ...}` to the authenticated profile session stream endpoint.
- `runtime/allies_runtime/profile_store.py` fingerprints immutable seeds and treats incompatible existing seeds as conflict/repair. Its existing configuration-preservation behavior and `runtime/tests/test_profile_store.py` make bulk seed changes an unnecessary state-migration risk.
- The orchestrator inspected Hermes source pinned at `36cb5ae5530a75def7df3195e49b7a4aa2add482` and the running Hermes image `sha256:d57aec5d9d91ca61b8b58c2031a7ff9536d34e45226ff975359899a9b7b19ade`. Both accept `model_options.reasoning` on session chat/stream and pass it into `_create_agent`; `_request_reasoning_config` takes precedence over `GatewayRunner._load_reasoning_config`. Root YAML alone does not establish effective model effort.
- Canonical knowledge inspected by the orchestrator and supplied as bounded snapshots: `projects/allies/index.md`, `engineering/specs/foundry-continuity-layer.md`, `engineering/specs/conversation-and-streaming.md`, `engineering/decisions/decision-log.md`, and `references/hermes-and-fly.md`. These establish Foundry runtime ownership, immutable profile identity, persistent state preservation, and unknown-safe execution dispatch. Snapshots are evidence, not replacements for canonical notes.
- Repository instructions, `ENGINEERING_STYLE.md`, both READMEs, `Makefile`, both `pyproject.toml` files, `scripts/validate.py`, CI, execution contract examples, and relevant claim, worker, Hermes, settings, and profile tests were inspected.

Use the existing claim boundary and native Hermes request support. Profile materialization is not needed to propagate this default and would add ownership metadata, merging, and migration failure cases without improving the requested behavior.

## Contract and behavior

1. Add Foundry setting `ALLIES_RUNTIME_REASONING_EFFORT`, default `xhigh`. Validate a small explicit allowlist of effort values supported by the pinned Hermes parser and the configured model; include `high` and `xhigh` for the tested update/rollback path. Reject blank, malformed, or unsupported settings at startup with a configuration error. Document the complete chosen allowlist alongside tests; do not silently downgrade an unsupported value.
2. Add optional `reasoning_effort` to the internal claim response and typed claim objects. It is Foundry-owned metadata, separate from Cloud's immutable execution input and fingerprint. New Foundry responses supply it; a new runtime receiving an older claim without it omits the Hermes override and retains legacy behavior. A present invalid value fails claim parsing before dispatch. No client-supplied execution field can change the managed setting.
3. Sample the setting when constructing each successful claim response, including a pre-dispatch replay after a lost response. The worker holds that value for its dispatched turn. An already dispatched stream does not change mid-turn, and this work adds no replay after dispatch. A pre-dispatch retry may adopt the current setting; exact effort persistence across that retry is intentionally unnecessary. Existing attempt, lease, idempotency, and tenant fencing remain authoritative.
4. Thread the optional value through `FoundryWorker`, `_stream_events`, and both Hermes stream methods. When present, serialize exactly `"model_options": {"reasoning": {"enabled": true, "effort": "xhigh"}}`, substituting the validated value. When absent, leave the legacy request shape unchanged. Apply to first turns and existing sessions, rather than only session creation. Preserve authentication headers, cancellation, timeouts, bounded parsing, approval behavior, and unknown-safe failure semantics.
5. Initial mixed-version adoption is explicit: old runtime consumers ignore the new claim field and do not gain the behavior. Adopt a compatible `allies-runtime` image once through the existing release process before declaring coverage of existing Allies. The inspected Hermes image already supports the request contract; no Hermes patch is planned. Later value changes require only Foundry configuration rollout, with ordinary process restart/reload and no per-machine edits. Configuration skew during a rolling Foundry restart may briefly produce either valid value; each dispatched turn retains the value it received.

## Implementation steps

1. **Setting and claim producer:** update `backend/config/settings.py`, `backend/runtime/services/claims.py`, and `backend/runtime/api/register.py`. Add settings and claim/API coverage in the existing backend test modules. Keep model resolution, profile seeds, and Cloud execution contracts unchanged.
2. **Runtime consumer and Hermes dispatch:** update `runtime/allies_runtime/foundry.py` and `runtime/allies_runtime/hermes.py`; adjust the existing fake clients/fixtures only where their signatures or claim shape need to reflect the additive field. Validate at the transport boundary and at direct Hermes-client entry points. Keep the shared stream helper consistent across buffered and incremental paths.
3. **Behavioral proof and documentation:** add focused tests below and a bounded native-Hermes contract test using the pinned parser/agent-construction path with provider calls stubbed. Record effective reasoning delivered to the agent/provider boundary, not just outgoing JSON. Document the setting, precedence, timing, mixed-version adoption, update, and rollback in `runtime/README.md` or the existing runtime operation documentation. Update the canonical Nabu specification/decision through the orchestrator when the accepted implementation changes the contract, using revision-aware read/write/readback.
4. **Review and delivery:** run focused checks, repository validation, separate simplicity and correctness/security reviews, and existing CI/Enkii gates at the final PR head. Aim for one reviewable 200–500-line PR including tests and docs; reassess if broader Hermes or schema changes become necessary. Retain the unmerged worktree. This task does not merge, publish images, or deploy.

## Acceptance and validation

| Case | Required evidence |
| --- | --- |
| New Ally | Default setting produces `xhigh` in the claim, stream payload, and native Hermes effective reasoning; session creation still uses Luna. |
| Existing Ally/session | A profile created before this change receives `xhigh` on its next compatible-runtime turn without rematerialization; an existing session receives the override too. |
| Second update and rollback | With the same profile, session, and runtime instance, subsequent claims under `xhigh` → `high` → `xhigh` produce those effective values. Simulate Foundry configuration reload in tests; no profile or image changes. |
| Configuration/state preservation | Snapshot configuration, manifest, SOUL, skills, memories, and session state around turns; assert no mutation caused by default propagation. Include a genuine explicit profile reasoning value: managed turns use the claim value while the stored override remains intact. |
| Compatibility and validation | Missing field omits model options; invalid present types/values fail before Hermes dispatch; invalid environment values fail startup. Both stream paths serialize the same structured option. Older runtime adoption is documented as incomplete coverage. |
| Timing and retries | A setting change after a claim is received cannot change that turn; a pre-dispatch claim replay may receive the new setting. Existing post-dispatch unknown-outcome tests remain green with no second model invocation. |
| Boundaries | Existing tenant isolation, lease fencing, approval continuation, cancellation, profile preservation, and keep-warm tests pass. No Cloud command schema, seed fingerprint, model default, or lifecycle timing changes. |

Focused commands from repository root (set `DJANGO_DEBUG=true` in the shell):

```text
uv run --locked --project backend pytest backend/runtime/tests/test_settings.py backend/runtime/tests/test_fnd005_backend.py backend/runtime/tests/test_fnd007_execution.py
uv run --locked --project runtime pytest runtime/tests/test_foundry.py runtime/tests/test_fnd007_worker.py runtime/tests/test_hermes.py runtime/tests/test_profile_store.py runtime/tests/test_profile_reconciliation.py
make check
make lint
make validate
```

Use `make format` when formatting is required. `make validate` runs locked dependency checks, Django checks, missing-migration detection, and backend/runtime suites with coverage; runtime coverage remains at least 90%. Existing CI additionally builds the runtime image, applies/verifies migrations, checks production configuration and static collection, and retains secret scanning/review gates. Run the native-Hermes contract test against the inspected source/image in an isolated local harness, with no real provider calls or live profile writes. Record its exact command and results in implementation evidence. If unavailable locally, report that gap and obtain equivalent CI evidence before claiming effective Hermes validation. Planning ran no product tests.

## Risks, rollback, and open decisions

- Higher effort may increase response time and cost. Existing limits remain in force; restore the previous validated Foundry setting and reload processes to roll back subsequent turns. In-flight turns finish under their sampled value.
- Request support is confirmed in the inspected Hermes versions, but later image changes can break precedence. Keep the native contract test tied to the adopted image/source. Do not claim coverage based only on a configuration-file inspection or an HTTP payload assertion.
- Removing the additive runtime support returns to Hermes' pre-existing reasoning behavior without persistent-state repair. Such a code rollback is separate from ordinary value rollback.
- Remaining implementation detail: verify the complete effort allowlist against the pinned parser/model before coding validation. No product decision, new preference schema, or approval gate is required. If the audit contradicts the assumed support or the native test cannot show effective effort, stop that dependent implementation step and report the evidence rather than introducing profile migration.
