# Bring-your-own OpenCode key (Zen/Go)

A tenant can point an Ally at their own OpenCode subscription instead of the
deployment default model. No Cloud dependency: the same provision payload works
from the provision API, a management command, or any custom cloud.

## Provision payload shape

Per profile seed:

- `provider`: `opencode-zen` (pay-as-you-go lineup) or `opencode-go`
  (open-models subscription lineup).
- `model`: any model id the chosen OpenCode lineup serves.
- `credential_refs`: exactly one entry mapping the provider env name to an
  **opaque reference, never the raw key**:
  - Zen: `{"OPENCODE_ZEN_API_KEY": "vault://tenant/zen"}`
  - Go: `{"OPENCODE_GO_API_KEY": "vault://tenant/go"}`

Raw keys are rejected at validation and must never appear in seeds, logs,
events, or manifests. Store the key once in the caller's secret store and fan
the same reference value into every profile seed for that tenant.

## Rotation runbook

Seeds are immutable: changing the reference value changes the seed fingerprint
and re-provisioning the same profile id conflicts. To rotate:

1. Store the new key and update the tenant reference target.
2. Re-provision every affected profile (delete + recreate through the normal
   lifecycle) with the new reference value.
3. Confirm re-materialization: a changed fingerprint forces a fresh `.env`
   (fully rewritten, `0600`); the old key is gone from the profile.

## Minimum Hermes version

The deployed Hermes image must register the `opencode-zen` and `opencode-go`
provider profiles (api-key auth against `https://opencode.ai/zen/v1` and
`.../zen/go/v1`). If a Zen/Go profile fails with an unknown-provider error,
upgrade the Hermes image before retrying.
