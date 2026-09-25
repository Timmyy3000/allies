# Live BYO model binding (static keys)

Change a live Ally's model credentials and selection without reprovisioning
and without losing its sessions. Static API keys only (OpenCode Zen/Go);
device-code/OAuth is a separate episode.

Key values never enter Foundry. Store the value in the secret store first,
then pass the opaque reference. All endpoints below are Cloud-authenticated
internal calls; the runtime applies changes before the next turn (under the
profile lock, never mid-turn) and records the binding generation.

## Install a key

`PUT /api/v1/internal/profiles/{id}/provider-keys`
`{"profile_id", "env_name", "reference"}` — e.g. `env_name:
OPENCODE_ZEN_API_KEY`, `reference: vault://tenant/zen`.

The runtime resolves the reference, fully rewrites the live profile's `.env`
(`0600`, server key preserved), and records the generation. A failed
resolution keeps the last-good files with a redacted `repair_required`
receipt.

## Select provider, model, reasoning

`PUT /api/v1/internal/profiles/{id}/model-binding`
`{"profile_id", "provider?", "model?", "reasoning?"}` — e.g. `provider:
opencode-zen`, `model: gpt-5.2`.

Every subsequent claim carries the effective selection (binding over seed
default) and the runtime forwards it per turn. An absent binding means the
deployment (org) default — Hermes picks up the switch next turn.

## Disconnect (revert to org default)

`DELETE /api/v1/internal/profiles/{id}/model-binding` clears the whole
binding in one step: the next claim falls back to the seed provider/model,
and the key set restores to exactly the seed refs (a live-apply rewrites
`.env` back to the org keys — nothing stale survives). No separate
remove-key call needed for a full revert.

`DELETE .../provider-keys/{env}` remains for dropping one installed key
while keeping the rest of the binding (e.g. rotating out a single
compromised key). Setting a new selection never wipes installed keys;
only clear does.

## Rotation

Re-install under the same env name with the updated reference: the generation
bump re-triggers the rewrite. Replays of an already-applied generation are
no-ops, so retries are safe. Seed re-provisioning is not required and sessions
survive.
