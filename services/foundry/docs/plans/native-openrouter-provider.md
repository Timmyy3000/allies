# Native OpenRouter provider

## Scope

Run the default Ally route through Hermes' native `openrouter` provider
instead of `openai-api` pointed at the OpenRouter base URL. Model
(`openai/gpt-6-luna`) and base URL are unchanged. Supersedes the vision
workaround in #110 and resolves the "native openrouter provider vs
openai-api+base-URL" decision left open in `default-model-gpt6.md`.

Out of scope: renaming the secret file path (`/run/secrets/openai-api-key`)
and the Fly secret `ALLIES_FND008_OPENAI_KEY`. Both already hold the
OpenRouter key; renaming them is secret plumbing with no behavior change.

## Why

`openai-api` makes Hermes assume api.openai.com wherever a code path does
not carry the live base URL. Vision auto-detect is one such path: every
`vision_analyze` call sent the OpenRouter key to OpenAI and got a 401. The
native provider is what Hermes supports for OpenRouter, and it also restores
OpenRouter model metadata and routing features.

## Approach

1. Settings defaults: provider `openrouter`, credential name
   `OPENROUTER_API_KEY` (same credential ref).
2. Migration `0035` (pattern of `0034`, forward and reverse): profiles whose
   seed exactly matches the `openai-api` default route move to `openrouter`
   with the renamed credential. Fingerprint is recomputed and materialization
   reset. Anything else is skipped.
3. Runtime `profile_store`: a managed `openrouter` seed exposes its
   `legacy_provider_seed`. On wake, when no current upgrade matches, every
   existing legacy upgrade is judged against that legacy seed, then
   `model.provider` in `config.yaml` is rewritten. Missing `.env` credential
   names are already appended by the credential refresh.
4. Claims read provider from the seed, so live sessions re-lock to
   `openrouter` on their next turn.

## Behavior change

Hermes runs `openai-api` on the Responses API (`codex_responses`); the
native provider uses chat completions. Reasoning effort still reaches
OpenRouter (`extra_body.reasoning` for `openai/*` models), and stored
Responses reasoning items are stripped by the chat-completions transport.

## Rollout

1. Promote the runtime release first. The new runtime is a no-op for
   `openai-api` seeds.
2. Deploy the backend (runs `0035`). Workspaces re-materialize on wake.

Rollback: reverse `0035`; the runtime keeps accepting both routes.

## Validation

- Backend: `DJANGO_DEBUG=true uv run --locked pytest runtime` (migration
  probe, settings defaults, provisioning digest).
- Runtime: `uv run --frozen pytest tests/test_profile_store.py`.
- Hermes at the pinned SHA: `openrouter` route resolves chat, auxiliary, and
  vision clients to OpenRouter with `OPENROUTER_API_KEY`.
