# Inbound file transfer v1

This document records the accepted Cloud and Foundry boundary for incoming files.
The complete engineering plan is in `docs/plans/cld-010-file-sharing.md`.
Production admission remains disabled until its release requirements pass.

## Ownership

Cloud owns file identity, owner access, message order, and immutable versions.
Foundry owns access by the assigned runtime profile and its working copies.
The runtime receives no Cloud service or object-store credential.

## Execution manifest

An execution input can contain an optional ordered `files` array. Each item has:

| Field | Type | Rule |
| --- | --- | --- |
| `file_id` | UUID string | Identifies one immutable Cloud file version. |
| `name` | String | Contains a safe base filename. |
| `media_type` | String | Contains the verified media type. |
| `size` | Integer | Is between 1 and 25,000,000 bytes. |
| `sha256` | String | Contains 64 lowercase hexadecimal characters. |

The array has 1 to 10 items. Its total size cannot exceed 50,000,000 bytes.
An execution needs text or files. A text-only command omits `files`; it does not
send `null` or an empty array. Existing text and bootstrap fingerprints stay
unchanged. The shared golden vectors are in
`docs/contracts/foundry-execution-file-input-v1.json`.

Cloud freezes the manifest in its existing dispatch outbox. No object URL,
temporary credential, or runtime path is part of the command. File preparation
must finish before claim and dispatch. A blocked file message holds later
messages for that Ally. Routine execution does not acquire file authority from
this conversation-message contract.

## Accepted bytes

The plan-relative route is `/internal/v1/accepted-files/{file_id}/content`.
The full route under the existing Cloud API mount is:

```text
GET /api/v1/internal/v1/accepted-files/{file_id}/content?binding_id={binding_id}&message_id={message_id}
Authorization: Bearer <service credential>
```

Foundry uses `ALLIES_CLOUD_URL` and `ALLIES_CLOUD_EVENT_SERVICE_TOKEN`.
Cloud checks the matching `ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN`.
The reverse-direction Cloud-to-Foundry credential is not valid for this call.

Service authentication does not establish file access. Cloud must also check
the accepted dispatch manifest, source message, binding, owner, and Ally.
Reserved files and foreign references are denied. The response streams bounded
bytes. It does not redirect to storage.

Foundry exposes bytes only through the current authorized attempt, profile,
and runtime generation. The backend derives Cloud scope from persisted state.
It does not trust replacement scope supplied by the runtime.

## Runtime commit

Foundry stages the complete set before it calls the model. It verifies each
size and hash, then commits the receipt and file directory. A failed or partial
set cannot start model execution. Transfer work must not stop lease renewal.

A repeated accepted command uses its committed receipt. It must not overwrite
a working copy that the Ally edited. Paths stay within the assigned profile.
Profile cleanup fences new work before it removes file data.

## Evidence and release

Unit tests cover the protocol and failure rules. They do not prove production
ingress limits, scanner operation, runtime isolation, or object-store behavior.
The backend round trip must verify file hashes and model invocation counts.
Production enablement also needs approved capacity and deletion integration.
Interface and real-device acceptance remain separate release requirements.
