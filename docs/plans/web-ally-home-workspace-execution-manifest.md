# Web Ally Home Workspace Execution Manifest

## Shared Context

- Work brief: `docs/plans/web-ally-home-workspace-brief.md`
- Accepted plan: `docs/plans/web-ally-home-workspace.md`
- User approval: 2026-08-28 `ship`
- Plan reviews: intentionally not run in this staged workflow; the user requested plan and ship steps separately and has not authorized code review or PR work
- Interface instructions: `AGENTS.md`, `ENGINEERING_STYLE.md`
- Cloud instructions: `AGENTS.md`, `ENGINEERING_STYLE.md`
- Implementation delegation: `always`, repository `.agent/kickoff.yaml`
- Execution boundary: implement and validate only; do not commit, push, run normal code review, create a PR, or merge

## Task 1 - Cloud Ally Collection

### Objective

Add the missing authenticated Workspace Ally collection endpoint and publish its generated OpenAPI shape without changing persistence.

### Dependencies

- None.

### Owned Files Or Systems

- Cloud worktree: `E:\Users\Oluwatimilehin\Documents\Programming\helpers\allies-cloud\.forest\worktrees\ft\local-staging-docker`
- `backend/allies/api/controllers.py`
- `backend/allies/api/schemas.py`
- `backend/allies/services/creation.py`
- Focused Ally API/service tests
- Cloud OpenAPI generation and focused contract assertions only

Do not edit the existing Docker, auth, Google-provider, settings, README, or local-environment changes already present in the worktree.

### Required Context

- Invoke the installed Ponytail skill at `full` intensity before editing.
- The accepted plan and repository safeguards take precedence.
- Reuse the existing Ally response serializer and Workspace capability boundary.
- No migration, pagination, conversation repair, per-Ally conversation query, or speculative summary metadata.

### Acceptance Criteria

- `GET /api/v1/workspaces/{workspace_id}/allies` returns `SuccessResponse<AllyListResponse>`.
- Authorized empty Workspace returns `{"allies": []}`.
- Rows are ordered by newest `created_at`, then UUID descending.
- Authorization is current Workspace `PROFILE_READ`; missing/foreign/inactive scope is privacy-safe.
- Binding and provisioning relations are loaded without N+1 queries.
- Existing create and retrieve behavior is unchanged.

### Validation

- Focused Ally tests.
- Focused OpenAPI/contract tests.
- `make check`.
- `make lint` if touched files require it.
- Confirm `makemigrations --check --dry-run` produces no migration.

### Required Result

- Files changed
- Tests and exact results
- Query/authorization evidence
- Assumptions
- Blockers
- Integration notes for regenerating the Interface client from the local Cloud schema

## Task 2 - Interface Contract, Onboarding, And Home

### Objective

Consume the published Cloud Ally/chat/activity contract, preserve public waitlist behavior, and implement the authenticated messaging-first `/home` experience.

### Dependencies

- Task 1 complete and local Cloud OpenAPI available.

### Owned Files Or Systems

- Interface worktree: `E:\Users\Oluwatimilehin\Documents\Programming\helpers\allies-interface\.forest\worktrees\web\feat\int-007-google-auth-account`
- Pinned/generated Cloud contract and `packages/cloud-client`
- Web onboarding presentation/completion boundaries
- New `apps/web/app/home/**` and focused `apps/web/lib/allies/**`
- Auth return defaults/private-query cleanup required by `/home`
- Focused tests and CSS modules

Preserve the existing local homepage and simplified sign-in changes unless the accepted plan explicitly supersedes a line.

### Required Context

- Invoke the installed Ponytail skill at `full` intensity before editing.
- Use existing Query/session/onboarding/avatar patterns and no new dependency.
- Messaging-first: compact Ally conversation list, selected thread, minimal header, sticky composer, mobile list-to-thread route.
- Real data only. Do not invent search, previews, timestamps, unread state, calls, reactions, groups, or dashboard panels.
- Poll activity every 1.5 seconds only while active and visible, with an 80-poll limit.

### Acceptance Criteria

- All 13 acceptance criteria in the accepted plan.
- Public waitlist tests remain green.
- Signed-out `/home` returns through Google sign-in to `/home`.
- Desktop drawer and mobile onboarding route both create a real Ally and select it.
- Real history, send, activity states, bounded polling, provisioning states, and responsive messaging layout work.

### Validation

- Focused cloud-client, onboarding, session, Home, reducer, and responsive tests.
- `bun run cloud:check`
- `bun run typecheck`
- `bun run lint:web`
- `bun run test:run`
- `bun run build:web`
- Browser verification at desktop and mobile widths against the local Docker Cloud.

### Required Result

- Files changed
- Tests and exact results
- Acceptance criteria status
- Assumptions
- Blockers
- Integration notes
