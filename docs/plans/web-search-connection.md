# Web Search Connection Plan

Route: full. HTML: not needed (decision recorded at kickoff; pass to workers).
Revision 2: applies the reconciled review dispositions listed under
[Review Dispositions](#review-dispositions).

## Feature Overview

- Problem: today allies get `web_search` and `web_extract` only through a
  provider key hand-added to each Hermes profile `.env`. Nothing in the product
  connects, grants, rotates or revokes that key, and new allies never get it.
- Target users: workspace owners who want their allies to research the web.
- Source docs and specs: the episode objective (`.episode/episode-state.md`),
  the evidence index (`.episode/how.md`) and the `PLATFORM.md` web rule (#35).
- Success outcome: on Account → Connections, the user picks a provider
  (Parallel, Tavily, Exa), pastes an API key, and flips per-ally switches.
  Connect runs one live test search and rejects a key the provider refuses.
  Granted allies' `web_search` and `web_extract` calls return results. Calls
  from ungranted allies, or from any ally in an unconnected workspace, are
  refused with an instruction to connect or turn it on in Connections.
  Disconnect or ungrant takes effect on the next call. The key is never stored
  outside Cloud.

## Lead Decision: How Web Search Reaches Hermes

| Concern | A) Relay through Cloud (Gmail pattern) | B) Env delivery into profile `.env` |
| --- | --- | --- |
| Where the key lives | Sealed in Cloud only (`common/vault.py`). Cloud sends it to the provider in the auth header of each request. | Plaintext in every granted profile `.env`, readable by any tool the agent can run in that profile. |
| Revocation | Live: `check_grant` runs on every call (`integrations/services/grants.py:119-141`). | Needs a push. The sandbox respawns the child on a `.env` change only when idle (`allies_profile_sandbox.py:824-828`). |
| New allies | Covered as soon as the grant switch is on. | Provisioning carries no credentials, so every new ally needs an explicit push. |
| Existing `.env` content | Untouched. | `apply_binding` rewrites `.env` to API_SERVER_KEY plus resolved refs (`profile_store.py:2849-2855`), so the binding path and the merge path (`profiles.py:1092-1136`) can clobber each other. A binding applies only at claim (`foundry.py:2543`). |
| Provider choice | Cloud picks the adapter from the stored backend. Hermes is pinned to the `allies` backend by image-level managed config (see [Backend pin](#backend-pin)). | Hermes auto-detects from env in a fixed order: tavily, exa, parallel ([hermes] `tools/web_tools.py:241-250`). A stray earlier key silently wins. |
| Latency | One more hop per call (Hermes → Foundry → Cloud → provider). See [Errors and latency](#errors-and-latency). | Direct provider call. |
| Code touched | Cloud tool handler and adapters, a Hermes web-provider plugin, one managed config file. The Foundry relay is already opaque: any slug matching `[a-z][a-z0-9_-]{0,31}` passes (`runtime/api/register.py:135,176-200`). | Cloud push service, Foundry endpoints, new-ally hooks and a reconcile loop. |
| Tool visibility per ally | Tools are always listed, as Gmail's are (`hermes-image/plugins/gmail/__init__.py`). Cloud refuses ungranted calls with an instruction. | No key means no tool. |

**Chosen: A.**

1. It keeps the key off the machine and makes revocation and new-ally coverage
   free, because grants are already read live on every call.
2. Hermes supports plugin web backends, but it does not pick one on its own
   when any legacy key is present. The dispatcher asks
   `_get_search_backend()` first ([hermes] `tools/web_tools.py:685`), which
   falls back to `_get_backend()`. That walks env candidates (tavily, exa,
   parallel, firecrawl, searxng, brave-free, ddgs) before it considers plugin
   providers (`tools/web_tools.py:241-269`). The registry's single-provider
   shortcut (`agent/web_search_registry.py:146-147, 207`) applies only when
   exactly one registered provider is available. The bundled parallel, tavily
   and exa plugins count as registered providers, so any legacy key defeats
   it. The backend therefore has to be pinned in config (see
   [Backend pin](#backend-pin)).
3. Foundry needs no change. B needs a push path, has a known clobber bug and
   restart latency, and leaves the auto-detect precedence trap in place.

### Backend Pin

Chosen location: an image-level Hermes managed-scope file,
`/etc/hermes/config.yaml`, added to the Hermes image by a Dockerfile `COPY`:

```yaml
web:
  backend: allies
  search_backend: allies
  extract_backend: allies
```

Why this location covers every multiplexed profile and every new ally:

- Hermes reads `/etc/hermes` as a root-owned managed layer whose values win
  per leaf over each profile's `config.yaml` ([hermes]
  `hermes_cli/managed_scope.py:1-5, 33, 52-71`). `load_config` deep-merges it
  on top of the user config (`hermes_cli/config.py:3396-3399`).
- Each profile child runs in a sandbox that read-only binds `/`
  (`allies_profile_sandbox.py:767-769`), so every child sees the same
  `/etc/hermes`. The child environment is an allowlist built by
  `_base_environment` (`allies_profile_sandbox.py:388-410`). It does not pass
  `HERMES_MANAGED_DIR`, so the default path applies.
- New allies get the pin with no Foundry change. The rejected alternative,
  writing `web:` into each profile's `config.yaml` through
  `_profile_config_bytes` (`profile_store.py:827-837`), would also need an
  upgrade step for existing profiles. That means more Foundry code, and a
  per-profile edit could undo it.

`search_backend` and `extract_backend` are the pins the review asked for.
`backend: allies` is in the same file because `_get_capability_backend` falls
back to `_get_backend()` whenever the specific backend reports unavailable
(`tools/web_tools.py:298-309`). The plugin's `is_available()` always returns
True (Gmail pattern), so that fallback should never fire. The extra line makes
sure it lands on `allies` if it does.

The image has no `/etc/hermes` today, so this file is its only managed-scope
setting.

## Plan Hygiene and Evidence Boundaries

Paths are repository-relative. `[hermes]` means files inside the pinned Hermes
image (`/opt/hermes`). The plan holds no machine identifiers, keys or user data.
Live-machine steps are written as behavior and kept in operator notes.

## User Stories

1. As a workspace owner, I want to connect web search with my provider and API
   key, so that my allies can research the web.
2. As a workspace owner, I want to know at connect time if my key is wrong, so
   that I don't find out from a failed search later.
3. As a workspace owner, I want to choose which allies can search, so that only
   those allies spend my provider credits.
4. As a workspace owner, I want to replace the key or disconnect, so that a
   leaked or expired key stops working immediately.
5. As an ally without access, when I call web search I get a refusal that
   tells me what to say: web search isn't connected or isn't on for me, and
   the user can turn it on in Connections (`PLATFORM.md:58`).
6. As an operator, I want no provider keys in profile `.env`, so that machine
   compromise or prompt injection can't read them.

## Scope

### In Scope

- Cloud: web search as an `IntegrationSecret` provider, with a connect/replace
  API that runs a live test search, grant and disconnect APIs, provider
  backends, and a relay tool handler.
- Hermes image: an always-registered `allies` web-provider plugin that relays
  search and extract, plus the managed-scope backend pin.
- Web: a Connections row and sheet with a provider select, a key field, status,
  per-ally switches, replace and disconnect. Cloud-client methods and OpenAPI
  regeneration.
- Rollout: connect the live workspace, then remove the hand-added
  `PARALLEL_API_KEY` lines in the same deploy that ships the plugin.

### Out of Scope

- Mobile UI.
- Usage metering, billing, per-turn spend caps or per-ally rate limits (see
  [Follow-ups](#follow-ups)).
- Providers beyond parallel, tavily and exa.
- In-chat "connect web search" prompts.
- Changes to the Foundry relay or to option B plumbing.
- Changes to `PLATFORM.md`.

### Dependencies and Assumptions

- `ALLIES_VAULT_KEYS` is configured in Cloud prod. Web search connect refuses
  with 503 when it is unset, even under `DEBUG` (see `connect` below), because
  `common/vault.py:32-35` would otherwise fall back to a fixed development key.
- Cloud reaches the provider APIs over HTTPS. Exact endpoints and auth headers
  are confirmed in PR 1 against the provider docs and the Hermes plugin sources
  ([hermes] `plugins/web/{parallel,tavily,exa}/provider.py`).
- The per-turn relay context (`tools.allies_routines.context`) is set for chat
  and routine turns. Outside it, `relay` returns
  `web_search_tool_unavailable` (`allies_safe_inputs.py:80-81`), and the plugin
  turns that into a refusal. PR 3's smoke and the live check prove both paths.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `services/cloud/backend/integrations/services/web_search.py` | `connect` | `connect(*, workspace, backend: str, api_key: str, user) -> IntegrationSecret` | `backend in BACKENDS`. Key matches the generic `[\x21-\x7e]{16,512}` (same rule as `model_keys/services.py:41`); no per-provider format regex. | The live secret. | 1. Refuse with `VaultUnavailable` (→ 503) when `settings.ALLIES_VAULT_KEYS` is empty, regardless of `DEBUG`. 2. Run one live test search (`query="allies connection test"`, `limit=1`, 8 s timeout) with the pasted key. Provider 401/403 → `IntegrationInvalid("web_search_key_rejected")` (→ 422). Provider 429, 5xx, timeout or malformed JSON → `IntegrationUnavailable("web_search_check_failed")` (→ 503). Nothing is stored on failure. 3. Lock the live row. If one exists, update `ciphertext`, `backend` and `key_hint` in place, so grants survive a key or provider change. Otherwise create a row with a random `account_ref_hash`. A concurrent-create `IntegrityError` → `IntegrationConflict` (→ 409). |
| same | `disconnect` | `disconnect(*, secret) -> str` | Live or revoked row. | `"deprovisioned"` or `"already_cleaned"`. | One transaction: set `revoked_at`, delete grants, wipe `ciphertext`. No remote revoke. |
| same | `execute_web_search_tool` | Same keyword signature as `execute_gmail_tool` (`gmail_tool.py:167-174`). | `WebSearchToolRequest` (strict): `action ∈ {search, extract}`; `query` 1–400 chars; `limit` 1–10; `urls` 1–5 http(s) URLs ≤ 2048 chars each. | `(status, dict)` | `resolve_tool_turn`, live secret, `check_grant`, unseal, backend call, byte budget. Never logs the query, URLs or key; logs backend, outcome and latency only. Error mapping in [Errors and latency](#errors-and-latency). |
| `.../services/web_search_backends.py` | `BACKENDS` | `dict[str, dict]` literal, one entry per provider | — | — | Each entry holds `label`, `search_url`, `extract_url`, `auth_header` (name and value prefix), `search_body(query, limit)`, `extract_body(urls)`, `parse_search(json)`, `parse_extract(json)`. One shared `_post(url, headers, body, timeout)` over `urllib` (no new dependency, same as Gmail). Small per-provider parse functions sit next to the dict. |
| `.../services/grants.py` | `_require_enabled` | `_require_enabled(provider: str)` | — | — | Becomes a per-provider table: Gmail and Calendar use `gmail_enabled()`; web search is always on. Add `PROVIDER_WEB_SEARCH = "web_search"`, `GRANT_USE = "use"`, `PROVIDER_GRANT_LEVELS[web_search] = ("use",)`, `ALLOWLISTS[(web_search, use)] = ("web search", "web extract")`. |
| `.../api/controllers.py` | `_apply_grant` | `_apply_grant(*, secret, ally, level: str, user) -> AllyIntegrationGrant \| None` | `level` already validated by the request schema. | The grant, or `None` for `"none"`. | Extracted unchanged from the Gmail `set_grant` body (`controllers.py:259-270`): `"none"` calls `revoke_ally_grant`; any other level calls `set_ally_grant`. Gmail's `set_grant` and the web search grant route both call it. |
| `hermes-image/plugins/web-allies/provider.py` | `AlliesWebSearchProvider` | `WebSearchProvider` subclass, `name="allies"`, search and extract both supported | — | Hermes shapes (`agent/web_search_provider.py` docstring) | `is_available()` always returns True: no probe, no cache. `search` and `extract` call the existing `relay("web_search", …)` (`allies_safe_inputs.py:74-113`) unchanged and pass Cloud's normalized result through. Every refusal or error becomes `{"success": False, "error": <instruction>}` using the mapping in [Errors and latency](#errors-and-latency). |

### API and Transport Contracts

| Consumer | Method and path / event | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Web client | `GET /api/v1/workspaces/{workspace_id}/integrations/web-search` | Session; `WORKSPACE_READ` | — | `SuccessResponse[WebSearchConnectionResponse \| null]` | 401, 404, 500. Safe to retry. |
| Web client | `PUT …/integrations/web-search` | Session plus origin/CSRF (`_require_origin`); `WORKSPACE_WRITE` | `ConnectWebSearchRequest {backend, api_key}` | `SuccessResponse[WebSearchConnectionResponse]` | 401, 403, 404, 409 (concurrent create), 422 (backend or key format; `web_search_key_rejected` when the provider refuses the key), 503 (vault unset or unavailable; `web_search_check_failed` when the provider can't be reached). Retrying is idempotent: the same input gives the same end state. The client does not retry automatically. |
| Web client | `POST …/integrations/web-search/grants` | as PUT | `SetGrantRequest`-shaped `{ally_id, level: "use" \| "none"}` | `SuccessResponse[AllyGrantResponse]` | 409 not connected, 422 ally outside workspace. Idempotent. |
| Web client | `DELETE …/integrations/web-search` | as PUT | `DisconnectRequest {confirm: true}` (existing schema) | 202 `SuccessResponse[DisconnectResponse]` | 422 without confirm. Idempotent (`already_cleaned`). |
| Foundry relay | `POST /api/v1/internal/foundry/integrations/tool`, `integration="web_search"` | Foundry service token plus turn identity (existing `IntegrationToolEnvelope`) | `arguments` as `WebSearchToolRequest` | 200 with a Hermes-shaped result | See [Errors and latency](#errors-and-latency). The serialized response body is at most 60 000 bytes, because Foundry turns anything over 64 KiB, or any status outside {200, 403, 409, 413, 422}, into 503 (`routine_tools.py:119-120`). |

The key is never echoed. Responses carry `key_hint` (last four characters)
only.

```json
PUT …/integrations/web-search
{"backend": "parallel", "api_key": "<pasted key>"}

200
{"success": true, "message": "Web search connected", "data": {
  "connection_id": "6a3e…", "backend": "parallel", "key_hint": "x9Qa",
  "connected_at": "2026-10-12T10:00:00Z",
  "ally_grants": [{"ally_id": "1f0c…", "level": "use", "updated_at": "…"}]}}

422
{"success": false, "error": "web_search_key_rejected",
 "message": "Parallel rejected this key. Check it and paste it again."}
```

```json
relay arguments → response
{"action": "search", "query": "q", "limit": 5}
  → 200 {"success": true, "data": {"web": [{"title": "…", "url": "https://…", "description": "…", "position": 1}]}}
{"action": "extract", "urls": ["https://…"]}
  → 200 {"success": true, "data": [{"url": "https://…", "title": "…", "content": "…", "raw_content": "", "metadata": {}}]}
unconnected → 403 {"error": "web_search_not_connected", "instruction": "Web search isn't connected for this ally. Connect it in Account → Connections."}
ungranted   → 403 {"error": "web_search_not_granted", "instruction": "Web search is off for this ally. Turn it on in Account → Connections."}
```

The review's sample wording said "Settings → Connections". The plan uses
"Account → Connections" because that is where the UI lives
(`account-connections.tsx`, mounted at `account-client.tsx:259`).

### Errors and Latency

Inside Hermes, every error path ends as
`{"success": False, "error": <instruction>}`. The model gets an instruction it
can pass on to the user. Stack traces and the key never reach it.

| Source | Condition | What Hermes' plugin receives | Plugin error text (instruction) | Retries |
| --- | --- | --- | --- | --- |
| Hermes | No relay context in this turn | `{"error": "web_search_tool_unavailable"}` (`allies_safe_inputs.py:80-81`) | "Web search isn't available in this context." | None. |
| Hermes ↔ Foundry ↔ Cloud | Network error, timeout, Foundry 503, oversize body | `{"error": "web_search_service_unavailable"}` after the existing two attempts (`allies_safe_inputs.py:99-113`) | "Web search is temporarily unavailable. Try again later." | Hermes `relay` makes 2 attempts. No other layer retries. |
| Cloud | 403 `web_search_not_connected` | 403 body with `instruction` | Cloud's instruction (see above) | None. |
| Cloud | 403 `web_search_not_granted` | 403 body with `instruction` | Cloud's instruction (see above) | None. |
| Foundry or Cloud | 413 request too large | 413 body | "That web search request was too large. Use a shorter query or fewer URLs." | None. Not reachable with the strict request limits; mapped for completeness. |
| Cloud | 422 invalid arguments | 422 body with `error` | "Web search rejected the request: <Cloud's field message>." | None. |
| Cloud | 409 (stale turn or binding from `resolve_tool_turn`) | 409 body | Cloud's instruction, or "Web search couldn't run for this turn." | None. |
| Provider | 401 or 403 | 200 `{"success": false, "error": "web_search_key_rejected", "instruction": "The web search key was rejected. Ask the user to replace it in Account → Connections."}` | Cloud's instruction | None. |
| Provider | 429 | 200 `{"success": false, "error": "web_search_rate_limited", "instruction": "The web search provider is rate limiting requests. Try again in a minute."}` | Cloud's instruction | None. Cloud does not retry. It answers 200, so Hermes does not retry either. |
| Provider | 5xx, timeout or malformed JSON | 200 `{"success": false, "error": "web_search_unavailable", "instruction": …}` | Cloud's instruction | None. |
| Cloud | Vault unavailable while unsealing | 200 `{"success": false, "error": "web_search_unavailable", …}` | Cloud's instruction | None. |

Provider failures return 200 because Foundry passes 200 through and Hermes
retries only on status ≥ 500 or a network error.

Timeouts and worst-case latency:

- Cloud → provider: search 15 s, extract 20 s. Connect's test search: 8 s.
- Foundry → Cloud: 25 s (`routine_tools.py:58`). Hermes → Foundry: 30 s per
  attempt, 2 attempts (`allies_safe_inputs.py:99-102`).
- Normal worst case: a provider that hangs costs at most 15 s (search) or 20 s
  (extract) plus relay overhead. Cloud answers 200 before Foundry's 25 s, so
  Hermes does not retry.
- Absolute worst case: Cloud itself hangs. Foundry gives up at 25 s and
  answers 503. Hermes retries once, and Foundry gives up again, for about 50 s
  in total before the tool returns "temporarily unavailable".
- Connect: at most 8 s for the test search plus the PUT itself.

Bounds:

- Search: description ≤ 500 characters; at most 10 results.
- Extract: content ≤ 15 000 characters per page. `raw_content` is sent empty.
- Byte budget: Cloud serializes the result with the response renderer's own
  encoder and measures the bytes. While the result exceeds 60 000 bytes,
  Cloud shortens the longest page's `content` and measures again. Search
  results are truncated by dropping trailing hits if needed. This counts bytes,
  not characters, so CJK text (3 bytes per character in UTF-8, 6 when escaped
  as `\uXXXX`) and emoji (4 bytes, 12 when escaped as a surrogate pair) stay
  within the cap.

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `IntegrationSecret` | `integrations/models.py:31` | add `backend: CharField(32)`, `key_hint: CharField(4)` | default `""` | Web search rows: `backend in BACKENDS`, `key_hint` = last four characters of the key, `ciphertext` sealed by `common.vault`, `scope_set=[]`, `account_email=""`. The existing one-active-row-per-provider constraint applies. | Additive migration `0004_integrationsecret_backend_key_hint`. Gmail rows keep `""`. Gmail disconnect never touches web search rows because the controllers are separate. |
| `AllyIntegrationGrant` | `integrations/models.py:71` | unchanged; `level="use"` | — | Same `(secret, ally)` uniqueness. | None. |
| `WebSearchConnectionResponse` | `integrations/api/schemas.py` | `connection_id: UUID`, `backend: Literal["parallel","tavily","exa"]`, `key_hint: str`, `connected_at: datetime`, `ally_grants: list[{ally_id: UUID, level: "use", updated_at: datetime}]` | all required | No key field exists. | New OpenAPI schema. |
| `ConnectWebSearchRequest` | same | `backend: Literal[...]`, `api_key: str (16–512)` | required | Strict; extra fields forbidden. | New. |
| `WebSearchGrantRequest` | same | `ally_id: UUID`, `level: Literal["use","none"]` | required | Strict; same shape as `SetGrantRequest` (`schemas.py:39-43`) with web search levels. | New. |
| `WebSearchToolRequest` | `services/web_search.py` | see above | — | Fields allowed only for their action (Gmail `_FIELDS` pattern). | Internal. |

### Frontend Interaction Shapes

| UI entry point | Hook / action signature | State shape and transitions | API input/output mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| `WebSearchConnection` row in `AccountConnections` (`apps/web/app/account/account-connections.tsx`) | `useQuery(webSearchConnectionQueryKey(workspaceId))` | `loading → disconnected \| connected \| error` | `getWebSearchConnection` → `{backend, keyHint, connectedAt, allyGrants}` | Skeleton row while loading. The error state offers "Try again". When disconnected the row reads "Not connected" with a Connect button. When connected it reads "Parallel · ending x9Qa" plus ally dots. Uses an existing icon; no new logo. |
| Connect/replace sheet | `connect({backend, apiKey}): Promise<void>` | `idle → submitting → done \| error`. The key input is cleared on success and on close. | `connectWebSearch(workspaceId, {backend, apiKey})` | Provider select (Parallel first and preselected; Tavily, Exa) with a "Get a key" link per provider. Password field (pattern from `ally-safe-inputs.tsx:230`, with `autocomplete="off"`). A client-side length check runs before submit. The submit button reads "Checking key…" while the test search runs. On 422 `web_search_key_rejected`: "<Provider> rejected this key. Check it and paste it again." On other 422: "That key doesn't look right." On 403: locked copy (`integrationAccessProblem`). On 503: "Couldn't check the key right now. Try again." |
| Detail sheet | `setAccess(allyId, enabled)`, `disconnect()` | About 20 lines of switch list and disconnect confirmation copied from `ConnectionDetail` (`account-connections.tsx:203-222`); `ConnectionDetail` itself is unchanged. | `setWebSearchGrant` (on → `"use"`, off → `"none"`), `disconnectWebSearch` | Optimistic `pending` switch exactly as Gmail. On error the switch reverts and inline copy appears. A "Replace key" action opens the connect sheet. |

## Phases

### Phase 1 — Cloud connection API and search backends (PR 1)

- Goal: store, test and grant web search per workspace, with no tool behavior.
- Work items:
  - Add the model fields and migration.
  - Add the provider constants, grant level and allowlist, and make
    `_require_enabled` per-provider.
  - Add `BACKENDS` with each provider's search request and `parse_search`,
    plus the shared `_post`. Connect's test search needs them.
  - Add `web_search.connect` (vault check, live test search, store) and
    `web_search.disconnect`.
  - Extract `_apply_grant` from Gmail's `set_grant` with no behavior change.
  - Add the `WebSearchController` (GET, PUT, POST grants, DELETE). It reuses
    `_live_secret`, `_ally_in_workspace`, `_read_error` and `_apply_grant`.
  - Add tests.
- Impacted: `integrations/{models,api/controllers,api/schemas,api/register,services/grants,services/web_search,services/web_search_backends}.py`, `integrations/migrations/0004_*`, `integrations/tests/test_web_search_api.py`.
- Exit criteria:
  - Cloud checks are green.
  - The OpenAPI schema exposes the four routes, and no field carries the key.
  - Gmail and Calendar grant tests pass unchanged.

### Phase 2 — Cloud relay tool (PR 2)

- Goal: granted allies' relayed calls reach the provider. Everything else is
  refused with an instruction.
- Work items:
  - Add `WebSearchToolRequest` and `execute_web_search_tool`, and register it
    as `_TOOLS["web_search"]` (`integrations/api/register.py:23-29`).
  - Add each provider's extract request and `parse_extract` to `BACKENDS`.
  - Add the size bounds, the 60 000-byte budget and the full error mapping.
  - Tests use recorded synthetic provider payloads with `urlopen` mocked.
- Impacted: `integrations/services/{web_search,web_search_backends}.py`, `integrations/api/register.py`, `integrations/tests/test_web_search_tool.py`.
- Exit criteria: Cloud checks are green, and one live call per provider with a
  test key passes in staging or locally (operator check, keys not committed).

### Phase 3 — Hermes `allies` web provider and backend pin (PR 3)

- Goal: `web_search` and `web_extract` always route through Cloud, whatever
  legacy keys or URLs sit in a profile's env.
- Work items:
  - Add `plugins/web-allies/{plugin.yaml,__init__.py,provider.py}`
    (`kind: backend`, `provides_web_providers: [allies]`).
  - Add `hermes-image/managed/config.yaml` with the [backend pin](#backend-pin).
  - Add Dockerfile lines next to the Gmail lines (`Dockerfile:183-186`):
    `COPY plugins/web-allies/ /opt/hermes/plugins/web/allies/` and
    `COPY --chmod=0644 managed/config.yaml /etc/hermes/config.yaml`, with
    `/etc/hermes` root-owned and not writable by the runtime user.
  - Add `smoke_web_search.py`, wired into `smoke_release.sh`. It runs a fake
    Foundry server inside the image and asserts:
    - In a turn context, both tools are in the tool definitions, and
      `web_search_tool` and `web_extract_tool` return the relayed results.
    - When the fake Foundry answers 403 `web_search_not_granted` or
      `web_search_not_connected`, both tools are still listed, and the call
      returns `success: false` with Cloud's instruction text.
    - With no turn context, the call returns the "isn't available" error and
      makes no network request.
    - Legacy override check: for each of `PARALLEL_API_KEY`, `TAVILY_API_KEY`,
      `EXA_API_KEY`, `FIRECRAWL_API_KEY` and `SEARXNG_URL` set alone, and then
      all of them together, `_get_search_backend()` and
      `_get_extract_backend()` return `allies`, and a `web_search` call reaches
      the fake Foundry. No request reaches any other host.
    - The managed file is root-owned and not writable by the runtime user.
- Impacted: `services/foundry/runtime/hermes-image/{Dockerfile,managed/config.yaml,plugins/web-allies/*,smoke_web_search.py,smoke_release.sh}`.
- Exit criteria:
  - The image builds.
  - The provider pytest, image pytest and `smoke_release.sh` pass.

### Phase 4 — Web UI and client (PR 4)

- Goal: the user can connect, grant, replace and disconnect from Connections.
- Work items:
  - Regenerate the OpenAPI from PR 1's Cloud schema (`cloud:fetch` with
    `ALLIES_CLOUD_OPENAPI_FILE`/`_REVISION`, then `cloud:generate`).
  - Add client methods, Zod schemas and mappers in `packages/cloud-client`.
  - Build the `WebSearchConnection` component and connect sheet. Copy the
    switch list and disconnect confirmation (about 20 lines) instead of
    extracting a shared component. Reuse an existing icon.
  - Add tests.
- Impacted: `packages/cloud-client/{openapi/*,src/generated/openapi.ts,src/client.ts,src/mappers/integrations.ts,src/schemas*}`, `apps/web/app/account/{account-connections.tsx,web-search-connection.tsx}`, `apps/web/lib/integrations/*`.
- Exit criteria: web checks are green, and the walkthrough works against a
  local Cloud.

### Phase 5 — Rollout and cleanup (operator, after all PRs merge)

The plugin and pin route every web call through Cloud from the moment the new
image runs. The workspace must therefore be connected and granted before the
image deploy, and the legacy keys come out in that same deploy.

1. Deploy Cloud (after PR 1 and again after PR 2), then the web app (after
   PR 4).
2. The user connects Parallel in the UI with the key they already own. The
   live test search must pass. They then turn on the allies that should search.
   Default: the six that have a key today.
3. In one maintenance window:
   1. Back up each profile `.env` root-only.
   2. Remove only the `PARALLEL_API_KEY` line from each, never printing values.
   3. Deploy the Hermes image through the standard runtime release path. Don't
      restart the Hermes container alone; that breaks the runtime netns and
      `/opt/data` permissions.
4. Verify:
   1. A granted ally's search goes through the relay (a Cloud log line with
      backend and outcome).
   2. An ungranted ally's call is refused with the "turn it on" instruction.
   3. No profile `.env` contains a web provider key.
5. Delete the `.env` backups right after verification passes.

Rollback: pin the previous Hermes image and restore the `.env` backups (both,
because the new image ignores legacy keys), or turn allies off and disconnect
in the UI. After step 5 there are no backups; rollback then means pinning the
previous image and having the user re-add the key by hand, or fixing forward.

## Acceptance Criteria

1. Connecting stores only ciphertext and `key_hint`. No API response, log line
   or relay result contains the key. In tests, the key appears in exactly one
   place: the provider request's auth header.
2. Connect runs one live test search. A key the provider rejects is not stored,
   and the user sees "<Provider> rejected this key".
3. Connect refuses with 503 when `ALLIES_VAULT_KEYS` is unset, with `DEBUG`
   on or off.
4. A granted ally can run `web_search` and `web_extract`. The results come
   from the selected provider in Hermes' shape and stay within the stated
   bounds. The serialized relay response is at most 60 000 bytes, including
   for CJK and emoji content.
5. An ungranted ally, or any ally in an unconnected workspace, still sees both
   tools. Calling either is refused with an instruction to connect or turn it
   on in Account → Connections.
6. Ungrant, disconnect or key replacement takes effect on the next call.
7. Replacing the key or switching provider keeps the existing grants.
8. A new ally gets web search by flipping its switch, with no machine-side
   change.
9. A legacy provider key or `SEARXNG_URL` in a profile's env does not change
   where web calls go: they always reach Cloud.
10. Every relay error code maps to an instruction, as listed in
    [Errors and latency](#errors-and-latency). A provider 429 is not retried
    by Cloud or Hermes.
11. After rollout, no profile `.env` on the live machine contains a web
    provider key, and granted allies still search.
12. Gmail and Calendar connect, grant and disconnect behave exactly as before.

## Backend Considerations

### Query Optimization Plan

- Hotspots: the relay handler (one turn lookup, one secret, one grant query, as
  Gmail does) and GET status (secret plus grants).
- Query shapes: `select_related` on the turn as in `resolve_tool_turn`.
- Expected change: a constant 3–4 queries per relay call and 2 for GET.
- Measurement: an `assertNumQueries` test on GET and on relay `search`.

### N+1 Prevention

- Relation access map: secret → grants. There's no per-grant ally access
  because the response uses `ally_id` only.
- The GET serializer reads `ally_id`, not `grant.ally` (unlike
  `controllers.py:84`).
- Guardrails: the query-count tests above.

### Detailed Unit Test Cases

- Happy path:
  - Connect for each backend, with the test search mocked as success.
  - Replace keeps grants and updates the backend and hint.
  - Grant on, then off.
  - Disconnect, then reconnect creates a new row.
  - Relay `search` and `extract` per backend.
- Validation and bad input:
  - Short or non-ASCII key; unknown backend.
  - Extra fields.
  - `limit` 0 or 11.
  - Six URLs; `ftp://`.
  - A 401-character query.
  - Fields that don't belong to the action; `action="status"` is rejected.
- Connect checks:
  - Test search 401/403 gives 422 `web_search_key_rejected`, and no row is
    created or changed.
  - Test search 429, 5xx, timeout or malformed JSON gives 503
    `web_search_check_failed`, and no row is created or changed.
  - `ALLIES_VAULT_KEYS` unset gives 503 with `DEBUG=True` and with
    `DEBUG=False`, and no provider request is made.
- Auth/RBAC boundaries:
  - A read-only member can't PUT, grant or DELETE.
  - Another workspace's ally can't be granted.
  - A bad Foundry token gives 401/403.
  - A relay for a stale binding or fingerprint is refused (existing
    `resolve_tool_turn`).
  - An unconnected workspace gives 403 `web_search_not_connected` with the
    instruction; an ungranted ally gives 403 `web_search_not_granted`.
- Idempotency/retry:
  - Repeated PUT with the same input.
  - Repeated grant.
  - Repeated DELETE gives `already_cleaned`.
  - Concurrent first connect gives one row and a 409 for the loser.
- Failure paths:
  - Provider 401/403 gives `web_search_key_rejected`.
  - Provider 429 gives `web_search_rate_limited`, with exactly one provider
    request made.
  - Timeout, 5xx or malformed JSON gives `web_search_unavailable`.
  - Vault unavailable gives `web_search_unavailable` on relay.
- Byte budget:
  - Oversized ASCII, CJK and emoji pages each produce a rendered response of
    at most 60 000 bytes, measured on the actual response content.
  - Within budget, nothing is truncated.
- Secret handling:
  - With `urlopen` mocked, the key appears only in the provider request's auth
    header: not in the URL, body, response, `caplog` output or exception text.
  - `caplog` shows no key, query or URL.
- Shared grant step: Gmail `set_grant` tests pass unchanged after `_apply_grant`
  is extracted.

## Frontend Considerations

### Data Path

- User action entry: Account → Connections → the Web search row.
- Client route/component: `AccountConnections` → `WebSearchConnection` →
  connect sheet or detail sheet.
- Client API route/proxy: `session.runCloudOperation` with `csrf: true` on
  writes and `retryTransient: false` on PUT.
- Backend endpoint: `…/integrations/web-search` routes.
- Response → UI model mapping: the mapper turns snake_case into
  `WebSearchConnection` and maps the backend to its display label.
- Error/loading/retry path: as in the interaction table. Errors go through
  `integrationAccessProblem`, generalized to take a label.

### State Management Considerations

- State ownership: React Query owns the server state. Sheet view and form
  fields are local component state. The key lives only in a local input and is
  never put in a store or query cache.
- Source of truth: the Cloud response. Ally dots derive from `allyGrants`.
- Caching/invalidation: `setQueryData` from the PUT and grant responses, and
  invalidation after DELETE.
- Concurrency: one pending switch at a time (existing Gmail pattern). The
  submit button is disabled while submitting.

## Test Plan

- Unit tests:
  - Cloud: `test_web_search_api.py` and `test_web_search_tool.py`, plus the
    existing `test_grants.py` and `test_api.py` unchanged and passing.
  - Web: mapper and schema tests; component tests for connect validation, the
    key-rejected message, connected and disconnected states, and switch revert
    on error.
- Integration/API tests: Django test-client tests for the four routes and the
  internal relay endpoint.
- Regression checks:
  - Gmail and Calendar API and grant tests.
  - `cloud:check`, to keep the OpenAPI in sync.
- Hermes smoke: `smoke_web_search.py` as described in Phase 3, including the
  legacy-key override check.
- Manual verification checklist (local Cloud plus a test key):
  1. Connect with a deliberately wrong key; check it is rejected and nothing
     is stored.
  2. Connect with the real key, and check the row and hint.
  3. Grant one ally.
  4. In chat, ask that ally a fresh-facts question and check that it searched.
  5. Ask an ungranted ally the same question. It says web search is off and
     can be turned on in Connections.
  6. Ungrant, then check the next call is refused.
  7. Replace the key; grants are kept.
  8. Disconnect.
  9. Then run the live rollout checks in Phase 5.
- Commands (no `make` on the VPS; run the underlying commands):
  - Cloud (`services/cloud/backend`):
    - `uv run python manage.py check`
    - `uv run python manage.py makemigrations --check --dry-run`
    - `uv run python manage.py migrate --noinput && uv run python manage.py migrate --check`
    - `uv run pytest`
    - `uv run ruff check . && uv run ruff format --check .`
  - Hermes image (`services/foundry`):
    - `uvx --from pytest==8.4.2 --with PyYAML==6.0.3 pytest runtime/hermes-image/provider/tests/test_provider.py runtime/hermes-image/tests -q`
    - Build the image as `runtime-images.yml` does, then run
      `sh runtime/hermes-image/smoke_release.sh <hermes-image-tag> <runtime-image-tag>`.
      Dry-run against `allies/hermes:local` first.
  - Web (repo root): `bun run cloud:check && bun run typecheck && bun run test:run && bun run lint:web && bun run build:web`.
  - Foundry backend and runtime: not run, because no Foundry code changes.

## PR Stack and Merge Order

Line counts exclude the migration file, generated code and the OpenAPI JSON.

| # | Branch | Base | Content | Est. lines | Depends on |
| --- | --- | --- | --- | --- | --- |
| 1 | `cloud/web-search-connection` | `nightly` | Phase 1: model, connect with live test search, grants (shared `_apply_grant`), disconnect, search backends | ~500 | — |
| 2 | `cloud/web-search-relay` | PR 1 | Phase 2: relay tool, extract backends, byte budget, error mapping | ~400 | 1 |
| 3 | `foundry/web-search-plugin` | `nightly` | Phase 3: always-registered plugin, managed-scope backend pin, smoke | ~250 | Runtime use needs 2 deployed and the workspace connected. Before that, every call is refused with an instruction. |
| 4 | `web/web-search-connection` | PR 1 | Phase 4 | ~400 | 1 (OpenAPI) |

Merge order: 1 → 2 → 4 → 3. Deploy Cloud after 1 and again after 2, and the
web app after 4. PR 3 merges last. Its image is deployed in the Phase 5
maintenance window, after the user has connected and granted, together with
the removal of the legacy `.env` lines.

## Risks and Mitigations

- Risk: a legacy env key or URL routes around Cloud.
  - Mitigation: the managed-scope pin, which wins per leaf over profile config,
    and the Phase 3 smoke that sets each legacy candidate and asserts dispatch
    still reaches Cloud. The legacy lines are also removed in the deploy that
    ships the plugin.
- Risk: a later Hermes upgrade changes managed-scope behavior or the web
  backend selection order.
  - Mitigation: the legacy-override smoke runs in `smoke_release.sh` for every
    image build, so a change fails the release.
- Risk: the image deploys before the workspace is connected, and searches stop
  working.
  - Mitigation: Phase 5 connects and grants before the image deploy. If the
    order slips, allies get a refusal that tells the user to connect.
- Risk: a provider response shape or endpoint drifts.
  - Mitigation: each backend is one dict entry with a parse-function test.
    Errors map to `web_search_unavailable` with an instruction, so the model
    reports the problem instead of looping.
- Risk: response size exceeds Foundry's 64 KiB cap, so every call returns 503.
  - Mitigation: the 60 000-byte budget on the serialized body, with ASCII, CJK
    and emoji tests.
- Risk: the key leaks through logs or errors.
  - Mitigation: never log arguments or keys; tests assert the key appears only
    in the provider auth header; the key is accepted only in the PUT body.
- Risk: a dev or misconfigured deploy seals keys with the fixed development
  key.
  - Mitigation: connect refuses when `ALLIES_VAULT_KEYS` is unset, regardless
    of `DEBUG`, with a test for both settings.
- Risk: two vaults sit in one table.
  - Mitigation: web search rows are handled only by `web_search.py`, which uses
    `common.vault`. A test asserts that Gmail's `disconnect_account` is never
    reachable for `provider_key="web_search"`, because the controllers are
    separate.
- Residual risk: prompt injection through extracted pages. The existing
  `PLATFORM.md` Boundaries rule (web pages are information, not instructions)
  already applies to the browser and applies equally here. No new mitigation in
  this stack.
- Rollback/fallback: PRs 1, 2 and 4 each revert on their own, and the migration
  is additive. For the runtime, pin the previous Hermes image and restore the
  `.env` backups until they are deleted in Phase 5 step 5.

## Owner Decisions

Settled:

1. Key check on connect: connect runs one live test search with the key (8 s
   timeout) and rejects a key the provider refuses, with a clear message. The
   key format check stays the generic regex; no per-provider format rules.
2. Grants on first connect: none. The user flips switches (Gmail parity).
   Phase 5 has the user grant today's six allies.
3. Launch providers: Parallel (preselected and recommended), Tavily, Exa.
4. `PLATFORM.md`: unchanged. Cloud's refusal instructions tell the ally what
   to say.
5. Tool visibility: always-present tools with a Cloud refusal, as Gmail does
   today.

## Follow-ups

- Per-turn or per-ally spend cap. Deferred: size and time bounds are enough for
  a single-user install. Revisit if provider bills surprise.

## Review Dispositions

| ID | Finding (short) | Disposition | Where applied |
| --- | --- | --- | --- |
| SIMP-1 | Drop grant-aware visibility machinery | Accepted (P0, merged with ADV-1) | Gmail pattern: plugin always registered, Cloud refuses. Status action, probe, plugin cache, `relay` keyword change, visibility smoke and old Risk 1 deleted. |
| SIMP-2 | (Superseded by SIMP-1) | Moot | No change needed after SIMP-1. |
| SIMP-3 | Backends shape | Accepted | `BACKENDS` is a dict literal per provider, with one `_post` and small per-provider parse functions. |
| SIMP-4 | No new logo, no `ConnectionDetail` extraction | Accepted | About 20 lines copied into the web search detail sheet; existing icon reused. |
| SIMP-5 | Keep the `backend` and `key_hint` columns and their additive migration | Accepted | Sealing them would make GET depend on the vault and unseal on every read. |
| SIMP-6 | Keep the 4-PR stack | Accepted | Stack kept. Search backends moved into PR 1 because connect's test search needs them. |
| SIMP-7 | Share the grant apply step; drop `.only()` | Accepted | `_apply_grant` extracted from Gmail's `set_grant`; `.only()` removed from the query plan. |
| ADV-1 | Status probe and visibility are fragile | Accepted (P0, merged with SIMP-1) | As SIMP-1. Acceptance criteria rewritten: ungranted calls refused with an instruction; revoke applies on the next call. |
| ADV-2 | Legacy env keys can route around Cloud | Accepted | Managed-scope pin in `/etc/hermes/config.yaml`; legacy-override smoke; legacy lines removed in the same deploy. |
| ADV-3 | Wrong "single-provider shortcut" citation | Accepted | Lead decision point 2 corrected with citations; pin added. |
| ADV-4 | 60 000 bytes counted as characters | Accepted | Byte budget on the serialized body; CJK and emoji tests. |
| ADV-5 | Error codes and latency unspecified | Accepted | [Errors and latency](#errors-and-latency) table and worst-case latency. |
| ADV-6 | `DEBUG` vault fallback could seal real keys | Accepted | Connect refuses when `ALLIES_VAULT_KEYS` is unset, regardless of `DEBUG`; tested. |
| ADV-7 | "Key never leaves Cloud" is inaccurate | Accepted | Reworded to "never stored outside Cloud"; test that the key appears only in the provider auth header. |
| ADV-8 | Rotate the Parallel key after migration | Dismissed | The user pastes the same Parallel key they already own; it has not leaked beyond their own machine. Kept: `.env` backups are deleted right after verification. |
| — | Per-turn spend cap | Dismissed (deferred) | Size and time bounds are enough for a single-user install. Listed under [Follow-ups](#follow-ups). |
| — | Prompt injection via extracted pages | Dismissed | The existing `PLATFORM.md` Boundaries rule covers it, as it does for the browser today. Residual risk noted in Risks. |
