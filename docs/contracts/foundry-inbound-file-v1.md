# Foundry inbound file v1

This contract stages one accepted Cloud file manifest for one Foundry attempt.
It does not publish files from Foundry to Cloud.

## Gates

`ALLIES_RUNTIME_FILE_INPUT_ENABLED` defaults to `true` in the Foundry backend
and runtime; set it to `false` only for an explicit shutdown. The publication
flag, `ALLIES_RUNTIME_FILE_PUBLICATION_ENABLED`, follows the same rule.
These defaults are not a capability
proof. Production use needs the Cloud delivery gate and a later
generation-aware release proof for the deployed backend and runtime.

## Transport

The runtime calls this Foundry endpoint with its existing runtime bearer token
and the current lease token:

```text
GET /api/v1/runtime/attempts/{attempt_id}/files/{file_id}/content
```

Foundry checks the current runtime workspace generation, attempt, profile
lifecycle, active lease, conversation source, and persisted file manifest. It
derives `binding_id` and `message_id` from the stored execution. It then calls:

```text
GET /api/v1/internal/v1/accepted-files/{file_id}/content?binding_id={binding_id}&message_id={message_id}
Authorization: Bearer <ALLIES_CLOUD_EVENT_SERVICE_TOKEN>
```

The runtime does not receive this Cloud credential. Routine executions have no
file authority from a conversation command.

## Staging

The runtime accepts at most 10 files, 25,000,000 bytes per file, and
50,000,000 bytes per manifest. It reads fixed 64 KiB chunks. It verifies each
size and SHA-256 value before it commits the manifest receipt.

The runtime writes all files to a private staging directory. It atomically
renames the completed directory into the assigned profile workspace. It sends
only a bounded descriptor and workspace-relative path to Hermes. It never
sends file bytes in the Hermes request.

The lease renewer runs while staging. Existing profile cleanup continues to
fence active leases. A replay with the same manifest reuses an intact receipt.
If an Ally edited a working copy, the replay creates a recovery directory. It
does not overwrite the edited copy.
