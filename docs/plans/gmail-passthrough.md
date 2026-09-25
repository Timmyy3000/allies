# Gmail Tool Relay — Foundry Slice Plan

_Route: fast. HTML required: no. Branch `ft/gmail-passthrough` (base `dev`).
Landing held: merges together with Cloud PR #55, never alone (D-F1).
Supersedes the earlier resolve-callback / token-file draft (adversarial verdict
Blocked; see "Why the design changed")._

## Objective

Let an Ally read and send Gmail for its workspace through the Gmail connection
and per-Ally grant that Cloud PR #55 already owns, with Foundry staying
provider-neutral and no Google credential ever reaching the Fly volume.

## Approach: reuse the routine-tool relay

The runtime already relays one Cloud-owned tool per turn:
Hermes `allies_routines` tool → Foundry `POST /api/v1/runtime/routines/tool`
(attempt-scoped signed capability from the claim) → Cloud
`POST /api/v1/internal/foundry/routines/tool` (service token) → Cloud executes
against the message/binding/fingerprint it dispatched. Gmail uses the same path:

1. **Hermes image (adapter):** new `allies_gmail` tool + `allies-gmail` plugin.
   It reuses the routine turn context (capability token + Foundry origin) that
   the existing patch already sets, and posts
   `{call_id, integration: "gmail", arguments}` to Foundry. The patch enables
   the `allies-gmail` toolset exactly when `allies-routines` is enabled
   (conversation turns with a capability; never routine-result streams).
2. **Foundry backend (kernel, provider-blind):** new
   `POST /api/v1/runtime/integrations/tool`. Same capability check as the
   routine relay; `integration` is an opaque bounded slug; forwards to Cloud
   `POST /api/v1/internal/foundry/integrations/tool`. The routine relay and the
   new relay share one forwarding helper.
3. **Cloud (PR #55 branch):** the internal endpoint resolves
   message → Ally → workspace exactly like the routine tool (binding and
   command-fingerprint checks), checks the live grant on every call, refreshes
   an access token in-process, calls the Gmail API, and returns compact JSON.

Actions: `search`, `get` (read grant), `prepare_send`, `send` (send grant).
`send` requires a `confirmation_ref` issued by `prepare_send` in an earlier
user turn of the same conversation, bound to the SHA-256 of the exact
recipients/subject/body/thread. One confirmation sends at most once. A retried
call with the same `call_id` replays the stored result; a send whose outcome
is unknown is never replayed blindly (the tool tells the Ally to check Sent).

## Why the design changed (adversarial findings)

| Finding | Disposition under the relay |
| --- | --- |
| ADV-F001 no pre-execution gate | Resolved by construction: every Gmail call is a Cloud request, so the live grant and send confirmation are checked before any Gmail API call. |
| ADV-F002 token-file freshness vs profile rebuild | Removed: no token file, no seed change, no profile rebuild. |
| ADV-F003 typed resolve input channel | Removed: the relay carries only message/binding/fingerprint identity already persisted for routines. |
| ADV-F004 process-local Cloud ref registry | Removed: Cloud refreshes per call; the mint/ref registry in PR #55 is deleted as dead code. |
| ADV-F005 FND ticket sign-off | No new lease/materialization semantics; the relay rides the existing FND-007 capability. |

Owner questions: Q1 (contract ownership) — the relay contract is the existing
Foundry→Cloud tool envelope plus an `integration` slug, defined here and served
by Cloud. Q2 — moot (registry removed). Q3 — existing tickets suffice. Q4 —
joint validation runs against the PR #55 head carrying the Cloud half.

## Scope

In: the three surfaces above, tests, and the Cloud removal of the unused
mint/ref registry. Out: Interface (Integrations page, in-chat connect UI,
approval card), routine-run (scheduled) Gmail use — the capability is only
issued for conversation turns — calendar scopes, and the Hermes
`google-workspace` skill (untouched, unused).

## Contract

Foundry request (runtime → Foundry), bearer = claim `routine_tool_token`:

```json
{"call_id": "<uuid>", "integration": "gmail", "arguments": {"action": "search", "query": "from:alice"}}
```

Foundry → Cloud (service token): the routine envelope plus `integration`:

```json
{"message_id": "…", "binding_id": "…", "command_fingerprint": "…",
 "call_id": "…", "integration": "gmail", "arguments": {…}}
```

Cloud statuses passed through: 200, 403 (`integration_unavailable`, grant
denied), 409, 413, 422 (invalid request / confirmation missing); anything else
becomes Foundry 503 `integration_service_unavailable`. Bodies ≤ 64 KiB.

## Boundary checks

- Foundry kernel carries no vendor naming: `integration` is an opaque slug;
  Gmail strings live in the Hermes adapter and Cloud only.
- No Foundry tables, migrations, or `ExecutionCommand` changes.
- Core boots and runs unchanged when Cloud has no Gmail connection (the tool
  returns `integration_unavailable`).

## Validation

- Foundry: `make check`, `make lint`, `make test APP=runtime/tests/test_integration_tools.py`
  plus the routine relay tests; `make runtime-test` unaffected.
- Hermes image: patch still applies (`git apply --check` in the image build);
  `make hermes-image-build` + `hermes-image-test` in CI.
- Cloud: `make check`, `make lint`, `make test APP=integrations`.
- Tests: relay auth and forwarding (Foundry); grant enforcement, read vs send,
  confirmation bound to payload and earlier turn, single use, call-id replay,
  unknown send outcome, disconnected account (Cloud).

## Risks and rollback

- Send safety rests on the confirmation rule; tests cover payload mutation,
  same-turn use, and reuse.
- Gmail API latency counts against the 10 s relay timeout; search/get return
  compact metadata only.
- Rollback: revert both PRs together; no migrations on Foundry, one additive
  migration on Cloud.
