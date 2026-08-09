# Allies runtime proof

`allies-runtime` is a small, independently packaged process for the FND-004
tenant topology. It calls Hermes only over authenticated loopback HTTP and
does not own a database or write the Hermes volume.

The image entrypoint uses `--serve` so the runtime remains the container's
PID 1. The proof harness is an explicit command:

Run the deterministic local proof from a clean repository checkout root:

```powershell
uv --directory runtime run --locked pytest --cov=allies_runtime --cov-report=term-missing
uv --directory runtime run --locked python -m allies_runtime --smoke fake
```

`--smoke live` is opt-in (`FND004_LIVE_SMOKE=1`) and still requires the
provider/lifecycle capability and secure temporary-profile bootstrap owned by
the live proof. The backend adapter is documented in
`docs/operations/hermes-runtime-smoke.md`. Without that gate it fails closed
and creates no resources. A live bootstrap prepares its socket/material seam
before provisioning, then installs temporary Hermes profiles within a bounded
timeout and confirms authenticated readiness before Foundry writes the durable
Workspace binding. Profile streams run only after that gate.

Configuration accepts an opaque `HERMES_CREDENTIAL_REF` only. The resolver
passed to `HermesClient` is responsible for retrieving a short-lived value;
the image's default resolver asks the secure workload-local Unix socket at
`/run/allies-runtime/hermes-credential.sock` (override with
`HERMES_CREDENTIAL_SOCKET`). The value is never placed in settings, payloads,
exceptions, or evidence. The socket/bootstrap is an explicit live-proof
dependency; a proof-only `test://fnd004/…` reference may instead use the
deterministic fixture resolver and needs no socket producer. Production secret
delivery and isolation remain later work.

## Foundry worker boundary

`allies_runtime.foundry.FoundryClient` calls the internal
`/api/v1/runtime/` contract with `Authorization: Bearer <runtime-token>` and,
for Attempt mutations, `X-Foundry-Lease-Token: <lease-token>`. Tokens remain in
process memory and are never included in errors or evidence. `FoundryWorker`
keeps a bounded pool (the proof uses two slots), serializes work through
Foundry's per-profile lease, and forwards Hermes events as they arrive. Event
IDs are deterministic from Attempt, stream, and sequence so response loss is
safe to replay with the same claim or mutation identity.

Renewal runs every 20 seconds against the 60-second lease contract. A renewal
failure cancels the incremental Hermes stream immediately, sends `stopped`,
and suppresses later event/terminal writes. The client maps `401`, `409`,
`422`, `429`, and `503` responses to typed errors; a lost claim response keeps
the same `claim_id` reserved until the replay succeeds.
