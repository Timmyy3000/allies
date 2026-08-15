# Nabu HTTP API fallback contract

Use this contract only when native remote MCP is unavailable or the user
explicitly requests HTTP. Discover the deployment first with
`GET ${NABU_URL}/agents.md`; do not assume a hosted URL or a different Nabu
version.

## Request conventions

- Set `NABU_URL` to the canonical deployment base without a trailing slash.
  Use HTTPS outside loopback. Preserve any configured base-path prefix when
  joining endpoint suffixes.
- Canonicalize with a standards-based URL parser: lowercase the hostname,
  preserve non-default ports and path prefixes, remove dot segments and the
  trailing slash, and reject credentials, query strings, fragments, empty
  hosts, and unsafe schemes. When deriving a base from an invite, remove only
  its final `/invites/<opaque-secret>` path segment.
- Send `Authorization: Bearer ${OWNER_BEARER}` for the owner surface or
  `Authorization: Bearer ${SCOPED_ACCESS_TOKEN}` for collaborator access.
  An owner session cookie from `POST /api/auth/login` may be used for HTTP
  fallback when the deployment permits it; never use that cookie for native
  MCP.
- Send `Content-Type: application/json` for JSON requests and
  `Accept: application/json`. URL-encode `path`, `q`, `tag`, and other query
  values. Keep credentials in memory only as long as needed and never put them
  in URLs.
- Check both HTTP status and the structured response body on every request.
  Never retry an unchanged invalid request or treat an HTTP error as success.
- Normalize every path as a vault-relative path. Reject empty/root paths for
  shared spaces, absolute paths, traversal, symlinks, and paths outside the
  vault. Keep containment segment-aware.

## Owner authentication

Use a deployment-provided owner bearer credential when available:

```text
Authorization: Bearer ${OWNER_BEARER}
```

For an HTTP-only owner session, submit the password without logging it:

```text
POST ${NABU_URL}/api/auth/login
Content-Type: application/x-www-form-urlencoded

password=${OWNER_PASSWORD}&redirect=%2Fagents.md
```

Persist the resulting session only in a secure cookie jar. Do not include the
password, cookie, or bearer value in this skill, a workspace file, logs, or
chat. Require owner authorization for every shared-space management endpoint.

### Owner-agent connection link

For non-technical owner onboarding, the human owner uses `Settings → Agents →
Connect an agent`, chooses `read` or `read/write`, and generates a one-time
connection URL. The agent must redeem the exact full URL; it must not fetch the
URL with `GET`:

```text
POST ${NABU_URL}/api/agent/connections/redeem
Content-Type: application/json

{ "connectionUrl": "${OWNER_CONNECTION_URL}" }
```

The URL expires after 10 minutes and can be redeemed once. A malformed,
expired, or already-used URL returns `410 AGENT_CONNECTION_INVALID`. A
successful response contains `credential`, `permissions`, `apiBaseUrl`,
`createdAt`, `expiresAt`, and `nextAction: "configure_agent"`; the durable
credential expires 90 days after issuance. Store it as `NABU_AGENT_TOKEN` (or
send it as `Authorization: Bearer ${OWNER_AGENT_CREDENTIAL}`) in the approved
secret store, never in a URL, chat, logs, or ordinary files. An owner-agent
credential is full-vault scoped with the selected write permission; it cannot
manage shared spaces. When it expires and returns `401`, have the owner issue a
new connection URL. Preserve any deployment path prefix when joining the
endpoint.

## Vault read and write surfaces

Treat `relPath` as the canonical note identity. Use these read endpoints with
the appropriate bearer credential:

```text
GET ${NABU_URL}/api/vault/
GET ${NABU_URL}/api/vault/index/stats
GET ${NABU_URL}/api/vault/tree
GET ${NABU_URL}/api/vault/folders?path=${URL_ENCODED_PATH}
GET ${NABU_URL}/api/vault/notes/${SLUG}
GET ${NABU_URL}/api/vault/notes/by-path?path=${URL_ENCODED_PATH}
GET ${NABU_URL}/api/vault/notes/neighborhood?path=${URL_ENCODED_PATH}
GET ${NABU_URL}/api/vault/search?q=${QUERY}&path=${URL_ENCODED_PATH}&tag=${TAG}&limit=${LIMIT}&offset=${OFFSET}
```

Use slug lookup only as a convenience because slugs can collide. Filter trees,
search, backlinks, neighborhoods, and graph-derived results to the caller's
scope; do not repeat hidden private paths.

Use these write surfaces:

```text
POST   ${NABU_URL}/api/vault/folders
DELETE ${NABU_URL}/api/vault/folders?path=${URL_ENCODED_PATH}
POST   ${NABU_URL}/api/vault/notes
PUT    ${NABU_URL}/api/vault/notes/by-path
PATCH  ${NABU_URL}/api/vault/notes/by-path
DELETE ${NABU_URL}/api/vault/notes/by-path?path=${URL_ENCODED_PATH}
```

Create a note with exactly one of `rawMarkdown` or `document`:

```json
{
  "path": "projects/example/note.md",
  "rawMarkdown": "# Example\n"
}
```

Use a structured document when canonical frontmatter metadata matters. Its
supported fields include `title`, `summary`, `tags`, `authors`, `source`,
`references`, and `body`. Do not send top-level `body` or `content`, and do not
send both `rawMarkdown` and `document`. Create folders with a vault-relative
`path`; delete folders only when they are empty and use non-recursive deletion.
Move a note with `{ "path": "from.md", "toPath": "to.md" }`; moves do not
rewrite wiki-links or Markdown links.

Read the note by canonical path after every mutation and verify content and
metadata. Successful mutations rebuild the in-memory index immediately.

### Revision-aware writes

Every note read returns `note.revision` and an `ETag`, for example
`"revision-42"`. Send the revision on updates and moves, especially with a
shared token:

```text
If-Match: "${REVISION_FROM_READ}"
```

Alternatively include `"expectedRevision": "${REVISION_FROM_READ}"` in the
JSON body. Use `expectedContentHash` for the parsed-note agent contract and
`expectedRawContentHash` only for a human source-save conflict check.

On `428 WRITE_REVISION_REQUIRED`, GET the supplied `readUrl`, merge the
intended change, and retry with the returned revision. On `409
STALE_NOTE_REVISION`, GET `readUrl`, merge against `currentRevision`, and retry.
Never silently overwrite newer content.

## Temporary shared spaces

Treat each shared space as a temporary, live, recursive boundary. Existing
descendants and files or folders created later beneath the shared root are
accessible until the lease expires or is revoked. Never share the vault root.
Reject symlinks and paths outside the vault, and do not use prefix matching
(`projects/example` does not contain `projects/example-private`). Choose a
narrower root instead of relying on exclusions; v1/v2 shared spaces have no
exclusion rules. A scoped token cannot access parents, siblings, symlink
targets, or metadata that reveals private paths.

Use `durationDays` from 1 through 183 inclusive. Omission uses the 7-day
default where supported. Access expires synchronously using server time;
cleanup may be asynchronous. Invite URLs are opaque one-time capabilities,
normally valid for one hour, and are not long-lived access tokens.

### Contract versions and compatibility

Prefer contract version 2. Send `contractVersion: 2` in v2 proposal and
confirmation bodies and feature-detect the same marker in responses. A v2
proposal binds the normalized path, duration, and permission set; confirmation
must repeat those values and must not silently change consent. Create a new
proposal after a mismatch or expiry.

If a proposal response has no `contractVersion: 2`, treat that proposal as v1
and confirm it using the v1 shape rather than creating a duplicate proposal.
Responses without a version marker retain v1 behavior. V1 redemption is
one-shot and is not retry-safe; v2 redemption uses the exact same
`Idempotency-Key` for at most one recovery request after an unknown outcome.

### Propose a scope

Call the owner-only endpoint:

```text
POST ${NABU_URL}/api/shared-spaces/proposals
```

Send the v2 body:

```json
{
  "contractVersion": 2,
  "path": "projects/example/shared",
  "durationDays": 14,
  "permissions": ["read", "write"]
}
```

Expect `201` with a recursive preview similar to:

```json
{
  "proposalId": "${PROPOSAL_ID}",
  "rootPath": "projects/example/shared",
  "files": ["projects/example/shared/readme.md"],
  "folders": ["projects/example/shared/subfolder"],
  "fileCount": 1,
  "totalBytes": 123,
  "warnings": ["${LIVE_RECURSIVE_SCOPE_WARNING}"],
  "liveRecursiveScope": true,
  "expiresAt": "${PROPOSAL_EXPIRY}",
  "contractVersion": 2,
  "durationDays": 14,
  "permissions": ["read", "write"]
}
```

Show the complete `files` and `folders` lists, counts, bytes, warnings,
proposal ID, and expiry to the human. State that later descendants are also
included. A proposal has no sharing side effect.

### Confirm and create an invite

After explicit human confirmation, call:

```text
POST ${NABU_URL}/api/shared-spaces/
```

Send the matching v2 consent fields:

```json
{
  "proposalId": "${PROPOSAL_ID}",
  "confirmed": true,
  "contractVersion": 2,
  "path": "projects/example/shared",
  "durationDays": 14,
  "permissions": ["read", "write"]
}
```

Require `confirmed: true`; never infer it from an earlier request. The
proposal must be unexpired and owned by the authenticated owner. Reject any
path, duration, or permission mismatch instead of changing consent silently.
Expect `201` containing `sharedSpaceId`, `rootPath`, `permissions`,
`sharedSpaceExpiresAt`, one exact `inviteUrl`, `inviteExpiresAt`,
`inviteUsesRemaining: 1`, and a v2 `redemption` descriptor. Send the invite
URL only to its intended collaborator; never log or persist it.

### Manage an owned space

Use these owner-only endpoints:

```text
GET  ${NABU_URL}/api/shared-spaces/
GET  ${NABU_URL}/api/shared-spaces/${SHARED_SPACE_ID}
POST ${NABU_URL}/api/shared-spaces/${SHARED_SPACE_ID}/revoke
POST ${NABU_URL}/api/shared-spaces/${SHARED_SPACE_ID}/invites
POST ${NABU_URL}/api/shared-spaces/${SHARED_SPACE_ID}/extend
```

The list response is `{ "spaces": [...] }`. A space includes
`sharedSpaceId`, `rootPath`, `permissions`, `sharedSpaceExpiresAt`, and
`revokedAt`. Creating another invite returns a new one-time `inviteUrl` and
its expiry. Revoke takes effect synchronously for existing scoped tokens.

Extend only after explicit confirmation:

```json
{ "confirmed": true, "durationDays": 7 }
```

Keep the resulting lease within the 1–183-day limit and never extend a revoked
or expired space. Collaborators cannot list, inspect, revoke, extend, or mint
broader spaces.

### Issue or revoke a read-only browser/API link

Owners may issue a separate read-only URL capability for a human browser or
an API client:

```text
POST   ${NABU_URL}/api/shared-spaces/${SHARED_SPACE_ID}/read-link
DELETE ${NABU_URL}/api/shared-spaces/${SHARED_SPACE_ID}/read-link
```

Issue it with an optional duration:

```json
{ "durationDays": 14 }
```

The response contains `shareUrl`, `sharedSpaceId`, `rootPath`,
`permission: "read"`, `durationDays`, and `expiresAt`. The opaque token is
only inside `shareUrl`. The default is 7 days, the allowed range is 1–183
days, and the effective expiry cannot outlive the shared-space lease. Each
space has one active read link: issuing another rotates the old one. `DELETE`
revokes the current read link without revoking the shared space and may be
repeated safely.

Treat `shareUrl` as a secret capability. Never log, persist, or commit it. A
human may open it in the browser; an API client may supply its `token` query
parameter on read-only endpoints such as `/api/vault/tree` or
`/api/vault/notes/by-path`. Read-link principals can access only the shared
root and descendants, cannot write, and cannot be upgraded by an agent.

### Redeem a collaborator invite (v2)

Call the deployment-relative endpoint exactly once initially:

```text
POST ${NABU_URL}/api/shared-spaces/invites/redeem
Content-Type: application/json
Idempotency-Key: ${IDEMPOTENCY_KEY}

{ "inviteUrl": "${INVITE_URL}" }
```

Use the exact JSON field `inviteUrl`; never substitute `invite`, `token`, or
`inviteToken`. Generate the idempotency key with at least 128 bits of entropy,
validate it against the deployment's allowed character and length rules, and
keep it out of logs and ordinary files. Do not GET the invite URL.

For a v2 server, send `Idempotency-Key` on the first request. If the network
outcome is unknown, make at most one recovery request with the exact same
invite URL and key. v2 returns the identical token and metadata for that
request. A different key is not a safe retry. A `410
SHARED_SPACE_INVITE_INVALID` means malformed, expired, redeemed, revoked, or
unavailable; ask for a new invite only after reporting the failure.

Expect `200` with these fields:

```json
{
  "contractVersion": 2,
  "sharedSpaceId": "${SHARED_SPACE_ID}",
  "rootPath": "projects/example/shared",
  "permissions": ["read", "write"],
  "sharedSpaceExpiresAt": "${SPACE_EXPIRY}",
  "accessToken": "${SCOPED_ACCESS_TOKEN}",
  "accessTokenExpiresAt": "${TOKEN_EXPIRY}",
  "profileId": "${PROFILE_ID}",
  "nextAction": "save_credential_profile",
  "links": {
    "tree": "/api/vault/tree",
    "rootFolder": "/api/vault/folders?path=${ROOT_PATH}",
    "noteByPath": "/api/vault/notes/by-path?path=${NOTE_PATH}",
    "search": "/api/vault/search?path=${ROOT_PATH}&q=${QUERY}"
  }
}
```

Treat only the four token-free, deployment-base-relative links returned by
Nabu as convenience links. Encode their allowlisted variables and preserve
the deployment base path. Use the access token as
`Authorization: Bearer ${SCOPED_ACCESS_TOKEN}` for subsequent in-scope calls.

### Persist and verify one scoped profile

Persist the token in an approved credential store shared by the agents,
sessions, and chats that will use this deployment. Key the profile by the
canonical `NABU_URL` and server-issued `sharedSpaceId`, not by an invite URL or
an ambiguous folder name. Store the following metadata with the secret:

- `NABU_PROFILE_VERSION=2`
- `NABU_API_BASE_URL`
- `NABU_SHARED_SPACE_ID`
- `NABU_ROOT_PATH`
- `NABU_PERMISSIONS`
- `NABU_ACCESS_TOKEN_EXPIRES_AT`
- `NABU_ACCESS_TOKEN`

Restrict access according to the platform secret store, write atomically when
the store supports files, reject symlinks or unsafe permissions, and never
shell-source an untrusted profile. If a file-backed profile is used, write the
exact seven-key allowlist atomically and keep it readable only by the current
user; do not silently cross between runtime credential directories. Do not put
the token in Markdown, source, chat, logs, or URLs. Verify the selected token
against `GET ${NABU_URL}/api/vault/tree` or another in-scope read before using
it. Treat a missing, expired, revoked, or failed profile as unusable; do not
request a broader scope automatically.

## Error handling

Use structured `code`, `nextAction`, `readUrl`, and `currentRevision` fields
when present:

- `400`: fix an invalid path, body, duration, permission, or key; do not retry
  unchanged.
- `401`: re-authenticate the owner or load a valid scoped bearer. Do not fall
  back from an invalid bearer to cookies or bootstrap.
- `403`: the principal lacks the required operation or path permission.
- `404`: the resource is missing or intentionally hidden outside scope.
- `409`: resolve a create/move conflict, source conflict, or stale revision by
  re-reading; do not overwrite newer data.
- `410 SHARED_SPACE_INVITE_INVALID`: stop using the invite and ask for a new
  one only when appropriate.
- `428 WRITE_REVISION_REQUIRED`: re-read the supplied resource and retry with
  the revision precondition.

Never expose private paths from errors, search results, backlinks,
neighborhoods, or graph responses.
