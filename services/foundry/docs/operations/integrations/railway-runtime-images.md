# Runtime release configuration on Railway

This optional integration applies the image pair saved by the runtime release
workflows to one Foundry project's shared variables. Local image validation
does not require Railway.

## Setup

- Set repository variable `RAILWAY_PROJECT_ID` to the Foundry project.
- Supply the existing account API token as secret `RAILWAY_TOKEN`. The command
  reads it as `RAILWAY_API_TOKEN`; do not substitute a project token using that
  authentication header.
- The workflows bind to GitHub environments `foundry / staging` and
  `foundry / prod`. Environment secrets may override repository secrets.
- Foundry API and publisher services must reference both
  `${{shared.HERMES_IMAGE}}` and `${{shared.RUNTIME_IMAGE}}`. A shared variable
  does not become a service variable merely because it exists.

The repository's current environments and `dev` branch have no protection rules.
Repository writers and manual workflow operators are trusted release operators;
the environment names alone do not impose an approval gate. Configure narrower
credentials or environment protection separately when that access model changes.

## Applying a pair

The workflows invoke:

```sh
python scripts/integrations/railway/update_runtime_images.py \
  --environment staging \
  --hermes-image 'ghcr.io/example/allies-hermes@sha256:<digest>' \
  --runtime-image 'ghcr.io/example/allies-runtime@sha256:<digest>'
```

The command resolves exactly one environment and reads both existing keys.
Both absent means initial setup; a partial or malformed pair fails before a
write. A matching pair is a no-op. Otherwise it sends both keys together through
`variableCollectionUpsert`, without replacing unrelated variables, and reads
them back. It outputs only the previous and verified image pairs, never other
variables or credentials. This is one collection operation, not a claim of a
transaction spanning service deployments or runtime machines.

An uncertain mutation response is followed by a readback before a bounded retry.
If the final state cannot be verified, the workflow fails. Do not assume the
write was rolled back: inspect the configured pair before retrying or selecting
a previous release. Avoid concurrent manual edits; Actions concurrency only
serializes these workflows.

Changing shared values can redeploy referencing services. Readback proves
desired configuration, not service deployment success or adoption by existing
runtime machines. Follow the [runtime canary and readiness procedure](../runtime-image-updates.md)
before declaring rollout complete.

API behavior: [Railway variable operations](https://docs.railway.com/integrations/api/manage-variables).
