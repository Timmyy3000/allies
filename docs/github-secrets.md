# GitHub Actions secrets

This file records secret names and their purpose only. Secret values must be added through GitHub and must never be committed here.

| Secret | Used by | Status |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | Enkii review and production release-note summarization | To be added |
| `PROMOTION_TOKEN` | Protected branch promotions and Fastlane back-merge PRs | To be added |
| `GITLEAKS_LICENSE` | Gitleaks scan for private-repository licensing, if required by the action | To be confirmed |
| `VERCEL_TOKEN` | Future Vercel deployment workflow, if GitHub Actions owns deployment | Not used yet |
| `VERCEL_ORG_ID` | Future Vercel deployment workflow | Not used yet |
| `VERCEL_PROJECT_ID` | Future Vercel deployment workflow | Not used yet |

The promotion credential should be a narrowly scoped GitHub App or fine-grained repository token with only the permissions required to update promotion branches and open the Fastlane back-merge PR.
