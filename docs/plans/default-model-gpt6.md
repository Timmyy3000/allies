# Default model switch: gpt-6-luna via OpenRouter

## Scope

Make `gpt-6-luna` via OpenRouter the default model for all allies: new
profiles via changed code defaults, existing default-config profiles via
a seed migration. Custom-provider profiles (non-default
provider/model/base-url/credential_refs) are skipped by exact-match
gating and keep working untouched. No quality eval (beta, owner
decision). Telemetry/pricing for the new model is a noted follow-up, not
a gate.

In scope: settings defaults, seed migration 0031 (forward + reverse),
runtime template/fingerprint/legacy path, base image bump to a build
containing the gpt-6 catalog, tests, rollout runbook (secret rotation +
deploy order). Out of scope: native openrouter provider plugin,
per-profile custom models (separate BYOS work), durable usage
accounting, Cloud changes.

## Approach

1. `backend/config/settings.py`: defaults become model
   `openai/gpt-6-luna` (fully qualified — OpenRouter routes on
   `author/slug`; a bare slug does not resolve), base URL
   `https://openrouter.ai/api/v1`. Provider stays `openai-api`;
   credential name `OPENAI_API_KEY` and ref
   `file:///run/secrets/openai-api-key` stay as-is — only the secret
   *value* rotates to an OpenRouter key at rollout (Railway var). No
   secret-plumbing code changes. Consequence of the qualified slug:
   gateway catalog lookups keyed on bare slugs miss (256K fallback
   window), which is harmless here because the absolute
   `threshold_tokens` cap fires regardless of the resolved window.
2. Seed migration `0031` (pattern of 0024/0030, forward + reverse):
   profiles whose seed payload exactly matches the old defaults
   (provider openai-api, model gpt-5.6-luna, base
   `https://api.openai.com/v1`, credential_refs `{OPENAI_API_KEY:
   file:///run/secrets/openai-api-key}`) get model rewritten to
   `openai/gpt-6-luna` and base URL rewritten to
   `https://openrouter.ai/api/v1`, fingerprint recomputed,
   materialization reset. Anything else
   (custom providers, already-migrated, drifted) is skipped untouched.
3. `runtime/allies_runtime/profile_store.py`: mirrored seed
   normalization/fingerprint/template (config.yaml model + base_url flow
   from the seed, so no template change expected beyond what the seed
   carries — verify during implementation), legacy upgrade path for
   pre-switch manifests.
4. Base image: KEEP the pinned base (`latest@b6f185…`, source
   `36cb5ae`). A bump to `v2026.9.24` was attempted and reverted:
   upstream split the god-files into satellite modules, so 10 of 11
   source-pinned patches no longer apply — rebasing them is a port, not
   a rebase, and belongs in separate maintenance. The switch does not
   need the new base: the old base already supports
   `compression.threshold_tokens`, unknown models degrade to the 256K
   fallback window (the absolute 100K cap governs regardless), and the
   model string passes through verbatim to OpenRouter. Patches are
   fail-closed at build; image CI is the verifier.
5. Tests: defaults, strict-shape, fingerprint parity backend↔runtime,
   migration probe (forward + reverse + idempotency), legacy upgrade.
6. Rollout (runbook in PR body): rotate `PROFILE_PROVISIONING_API_KEY`
   value to OpenRouter key → backend deploy (migration) → image release
   → workspaces re-materialize on wake. Implementation must verify the
   Fly provider-key secret is re-synced on wake (not just at provision);
   if wake reuses a stale secret value, the runbook gains a re-push step.

## Affected surfaces

- `backend/config/settings.py` (3 defaults), `backend/runtime/services/profiles.py`
  (migration matching), migration `0031`, related tests.
- `runtime/allies_runtime/profile_store.py` + tests.
- `runtime/hermes-image/Dockerfile` (base digest + source SHA).
- `env.fly.local.example`, docs mentions of the default model (follow
  the 0030 precedent: update where the default is stated).
- No API/schema changes; no Cloud changes.

## Acceptance

- New profiles materialize with gpt-6-luna + OpenRouter base URL and
  the pinned catalog window.
- Existing default-config profiles migrate (seed, fingerprint,
  re-materialization) and reach `EXISTING` without state loss;
  custom-config profiles are byte-identical before/after.
- Migration reverses cleanly (downgrade restores old defaults).
- Image builds with all patches applied (fail-closed); smoke suite green.
- Full backend + runtime suites green; lints clean.

## Validation

- Targeted: new/changed tests listed in step 5.
- Integrated: `make test APP=runtime/tests`, `make runtime-test`,
  `make lint`, `make runtime-lint`.
- Live (post-deploy, owner): new ally provisions on 6-luna; an old
  default ally re-materializes and answers; custom-provider ally
  untouched.

## Risks

- Upstream patch drift: 11 source-pinned patches against a 7-week-newer
  base. Guard: build fails closed on rejected hunks; image CI must pass.
  If a patch fails, options are rebase-the-patch (in scope) or hold the
  base and ship without the catalog (defeats the purpose — escalate).
- Secret rotation ordering: machines started between migration and key
  rotation would carry the new base URL with the old key. Guard: runbook
  orders rotation first; entrypoint writes the key at machine start.
- OpenRouter as a new third party for user content: privacy/DPA review
  is owner's call, outside this PR.
- Rate limits move, not away: per-turn burn unchanged by this PR; Track
  A work continues to matter on every provider.

## Unresolved decisions

- Compression model/hosting for the summarizer (Track A follow-up).
- usage_pricing entries for gpt-6 (telemetry-only; verify upstream
  coverage during implementation, file follow-up if missing).
- Native openrouter provider vs openai-api+base-URL: plan picks the
  latter (least change); explicit if owner disagrees.
