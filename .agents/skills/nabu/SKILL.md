---
name: nabu
description: Work with self-hosted Nabu knowledge spaces through native remote MCP first, including owner-agent connection links, bearer authentication, shared-space invites, scoped credentials, note traversal, and revision-aware mutations. Use when an agent must discover, authenticate, read, write, share, redeem, or verify Nabu data, or use the HTTP API because MCP is unavailable or explicitly requested.
---

# Nabu agent contract

Use Nabu as a shared knowledge space for humans and agents. Keep the
filesystem-backed vault as the source of truth and keep private knowledge
inside the caller's authorized scope.

## Discover the deployment and use native MCP first

1. Normalize the deployment to one canonical base URL with a standards-based
   URL parser. Require HTTPS except for explicitly configured loopback
   development, preserve ports and path prefixes, remove the trailing slash,
   and reject credentials, query strings, fragments, empty hosts, and unsafe
   schemes. Never derive the base from a `Host` header or untrusted origin.
2. Read `${NABU_URL}/agents.md` before operating when the deployment, version,
   or authentication contract is uncertain. Use its contract-version signals
   for shared-space compatibility.
3. Connect to `POST ${NABU_URL}/mcp` with stateless Streamable HTTP. Send
   `Authorization: Bearer <credential>`; do not use browser cookies or URL
   query tokens for MCP.
4. Use the owner bearer for the owner surface and a shared scoped bearer for
   collaborator access. Treat an invalid bearer as an authentication failure;
   never downgrade it to bootstrap access.
5. Treat a request without `Authorization` as bootstrap only. It exposes
   `redeem_shared_space_invite` and nothing else.
6. Use the HTTP API only when MCP is unavailable or the user explicitly asks
   for HTTP. Read [the HTTP fallback contract](references/api-contract.md)
   before constructing an HTTP request.

Do not use browser automation for normal note operations. Use a browser only
for human navigation or explicit UI testing. Treat local stdio MCP as a
separate, explicitly configured integration; do not substitute it for the
native remote endpoint silently.

## First-run setup by role

- **Owner/deployer:** If the host already has a `nabu` remote MCP connection,
  reuse it and its stored owner bearer; do not ask for the password again. If
  it is not configured, ask for the deployment base URL and have the owner put
  the credential into the host's approved secret or environment mechanism.
  Never collect or store the password in chat, Markdown, or ordinary files.
  For non-technical onboarding, the human owner can use `Settings → Agents →
  Connect an agent`, choose `read` or `read/write`, and generate a one-time
  connection URL. Redeem the full URL exactly once with
  `POST /api/agent/connections/redeem`; do not GET, log, or echo it. The
  response contains a durable owner-agent bearer and `expiresAt` (90 days
  after issuance). Store the bearer in the approved secret store as
  `NABU_AGENT_TOKEN` and use it for remote MCP or HTTP. It is full-vault scoped
  with the selected write permission, but cannot administer shared spaces. If
  the durable bearer expires or returns `401`, ask the owner to generate a new
  connection URL. Verify the connection with `get_vault_summary` before
  managing notes or shared spaces.
- **Collaborator:** Accept one invite URL; no Nabu account, password, or
  separate deployment is required. Parse the URL with a URL parser, preserve
  any deployment base path, and connect anonymously to that deployment's
  `/mcp`. Confirm that the bootstrap surface exposes only
  `redeem_shared_space_invite`, redeem the exact URL with an agent-generated
  idempotency key, save the returned scoped credential profile, reconnect with
  its bearer, and verify the scoped tree. Reuse that profile on later sessions
  and chats instead of asking for another invite. Never fetch the invite URL
  directly, echo it back, or save it.

## Select tools by principal

Use the normal vault tools for authorized note work:
`get_vault_summary`, `search_notes`, `read_note`, `list_folder`,
`get_neighborhood`, `create_note`, `update_note`, `move_note`, and
`delete_note`. Shared credentials expose only resources inside their live
scope; read-only credentials cannot mutate notes.

Use these owner-only shared-space tools:

- `propose_shared_space`
- `confirm_shared_space`
- `list_shared_spaces`
- `get_shared_space`
- `revoke_shared_space`
- `create_shared_space_invite`
- `extend_shared_space`

Use `redeem_shared_space_invite` for collaborator onboarding. Pass the exact
`inviteUrl` returned by Nabu. Do not fetch the invite URL directly, rename the
field, or treat it as a long-lived bearer token.

## Share safely

1. Propose a vault-relative folder and inspect the complete recursive preview:
   `files`, `folders`, `fileCount`, `totalBytes`, `warnings`, proposal ID, and
   expiry.
2. Require explicit human confirmation before calling
   `confirm_shared_space` with `confirmed: true`. Never infer confirmation
   from the proposal request or earlier wording.
3. Keep the shared root non-empty, vault-relative, segment-aware, inside the
   vault, and free of symlinks. Never share the vault root.
4. Treat a shared space as a live recursive boundary. Descendants that exist
   now or are created later are in scope; siblings, parents, prefix matches,
   symlink targets, and private linked results are not.
5. Enforce `durationDays` from 1 through 183 inclusive. Use the 7-day default
   only when the deployment permits omission. Require `read` permission and
   add `write` only when intended. Revoke or extend only as the owner and only
   with explicit confirmation where required.

## Redeem and persist scoped access

1. Call `redeem_shared_space_invite` from the bootstrap surface with the exact
   `inviteUrl`. For v2, provide a fresh high-entropy `idempotencyKey`; the
   HTTP fallback maps this value to the `Idempotency-Key` header.
2. If redemption has an unknown network outcome, make at most one recovery
   request with the same invite URL and the same idempotency key. v2 returns
   the identical token and metadata. Never retry with a different key or claim
   success without a successful response.
3. Save the returned scoped token and non-secret metadata in an approved
   credential store keyed by the exact canonical `NABU_URL` and
   `sharedSpaceId`. Make that profile available across agents, sessions, and
   chats. Never put passwords, cookies, invite URLs, bearer tokens, or
   idempotency keys in chat, Markdown, source files, ordinary workspace files,
   logs, or commits.
4. Reuse the persisted profile for later turns. Verify it immediately against
   the scoped tree or another in-scope read before reporting access as ready.
   If the token is missing or verification fails, inspect the credential store
   and report the failure before requesting a new invite.

## Read and write notes safely

- Use vault-relative `relPath` as the canonical note identity. Prefer
  `read_note` or the HTTP by-path endpoint over slug lookup.
- Read before changing. Preserve the returned revision and use revision-aware
  updates and moves. On `409 STALE_NOTE_REVISION` or `428
  WRITE_REVISION_REQUIRED`, re-read the supplied resource, merge the intended
  change, and retry; never silently overwrite newer content.
- Send exactly one of `rawMarkdown` or structured `document`, not top-level
  `body` or `content`. Verify every mutation by reading the canonical path
  again and checking content and metadata.
- Check the status and structured body of every request or tool result. Do not
  expose private paths or derived results outside the caller's scope.

For HTTP method, body, response, error, revision, read-link, and
credential-profile schemas, use [references/api-contract.md](references/api-contract.md).
