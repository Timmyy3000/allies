# GitHub Actions secrets

This file records secret names and their purpose only. Secret values must be added through GitHub and must never be committed here.

| Secret | Used by | Status |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | Enkii review and production release-note summarization | To be added |
| `PROMOTION_TOKEN` | Protected branch promotions and Fastlane back-merge PRs | To be added |
| `GITLEAKS_LICENSE` | Gitleaks scan if the action requires licensing | To be confirmed |
| `DEPLOYMENT_TOKEN` | Future hosted Foundry deployment workflow | Not used yet |
| `RAILWAY_TOKEN` | Optional runtime staging/publication and production promotion integration | Account API token, passed as `RAILWAY_API_TOKEN`; see [integration setup](integrations/railway-runtime-images.md) |

The promotion credential should be a narrowly scoped GitHub App or fine-grained repository token with only the permissions required to update promotion branches and open the Fastlane back-merge PR.

## Repository variables

| Variable | Used by | Status |
| --- | --- | --- |
| `STAGING_URL` | Public HTTPS staging readiness verification on pushes to `staging` | Required for the push-triggered gate; set to the public base URL, for example `https://staging.example.com` |
| `RAILWAY_PROJECT_ID` | Foundry Railway project selected by the image publishing workflow | Required at repository scope |

The verifier also supports a manual `workflow_dispatch` URL input. It requires
an `https://` URL and checks `/healthz` until the service returns HTTP 200 with
`{"status":"ok"}`.

Runtime publishing now targets staging only. Production promotion takes an
explicit saved release ID and reuses both immutable image references without
rebuilding. Use the [runtime release procedure](runtime-image-updates.md) for
selection, retries and rollback. The built-in `GITHUB_TOKEN` needs package/release
writes for publishing; production only reads packages/releases. PR validation
has no publishing or deployment permissions.

Runtime publication and production promotion each serialize their own runs.
Staging can advance independently. Selecting an older production release is an
intentional rollback, so review the selected ID before dispatch. Existing machine
adoption is a separate canary/readiness check.
