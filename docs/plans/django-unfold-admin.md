# Django Unfold Admin

## Status

- Type: improvement with a waitlist visibility bug fix
- Implementation delegation: never
- Delegation source: Kickoff fallback default
- Review worker: Codex direct model `gpt-5.6-terra` at `xhigh`, from `docs/plans/kickoff.yaml`
- Planning mode: fast; the work is bounded to Django admin configuration, registration, and tests with no schema or public API change
- Worktree manager: Forest
- Branch: `ft/django-unfold-admin`
- Worktree path: `E:\Users\Oluwatimilehin\Documents\Programming\helpers\allies-cloud\.forest\worktrees\ft\django-unfold-admin`
- Task workspace: `docs/plans/`
- Created: 2026-08-19
- Target date: not specified
- Current phase: PR #9 final review follow-ups in validation

## Objective

Make existing waitlist entries visible to authorized Django admin users and use Django Unfold consistently across the Allies Cloud admin.

## Context

`backend/waitlist/admin.py` explicitly states that waitlist models are not exposed, so Django never registers `WaitlistEntry`. Existing auth and workspace admin classes inherit from Django's default `ModelAdmin`. Unfold's current quickstart requires `unfold` before `django.contrib.admin` and requires custom admin classes to inherit from `unfold.admin.ModelAdmin`. Current release 0.104.1 supports the repository's Django 6.0 and Python 3.13 baseline.

## Requirements

- Register `WaitlistEntry` with the default admin site.
- Give operators a useful list view with `public_id`, `name`, `email_normalized`, `joined_at`, `expires_at`, and `created_at`; do not invent a lifecycle status absent from the model.
- Make every displayed waitlist field read-only, omit stored attempt/completion digests from the form, and disable admin-created entries.
- Emit timestamped, privacy-safe structured audit events for successful waitlist list/search/detail reads and single/bulk deletions without logging search terms or waitlist content.
- Install and configure Django Unfold according to its current official quickstart.
- Convert every repository-owned Django admin class to Unfold's `ModelAdmin` so admin pages remain consistently styled.
- Preserve existing model, database, public API, and admin URL behavior.

## Acceptance Criteria

1. `WaitlistEntry` is registered and appears in Django admin for staff with the normal Django model permissions.
2. The waitlist changelist exposes the specified operational columns, searches `public_id`, `name`, and `email_normalized`, filters by creation/join timestamps and consent version, and orders newest first.
3. The waitlist change form exposes only `public_id`, configuration/content fields, generation/reply/join timestamps, email, consent, expiry, and audit timestamps; all are read-only. Attempt ID/token/completion digests are absent. Add permission is always denied; only Django's explicit view permission grants list/detail access, change permission grants neither read nor write access, and deletion continues to require Django's delete permission.
4. Successful changelist/search and detail reads emit structured access events containing only opaque public actor/entry references and a search-used boolean; search terms and waitlist content never enter the log envelope.
5. `unfold` loads before `django.contrib.admin`, and all seven repository-owned admin registrations inherit from `unfold.admin.ModelAdmin`.
6. The existing `/admin/` URL remains unchanged and Django's system checks pass.
7. Focused admin permission/visibility/audit regression tests and all CI-equivalent checks pass.

## Evidence And Sources

- `backend/waitlist/admin.py`: deliberate non-registration is the direct cause of the missing entries.
- `backend/auths/admin.py` and `backend/workspaces/admin.py`: current repository-owned admin classes use Django's default `ModelAdmin`.
- `backend/config/settings.py`: `django.contrib.admin` is installed without Unfold.
- `backend/config/urls.py`: the default `/admin/` mount can remain unchanged.
- Local Git history: CLD-008 PR #8 is already merged into `dev` as `223f959`; Nabu's 2026-08-14 delivery note still describing it as under review is stale.
- [Unfold quickstart](https://unfoldadmin.com/docs/installation/quickstart/): app ordering and `ModelAdmin` inheritance requirements.
- [django-unfold](https://pypi.org/project/django-unfold/): current 0.104.1 release and runtime compatibility evidence, verified against PyPI's JSON metadata on 2026-08-19.
- `pip-audit 2.10.1`: an exact-pin audit of `django-unfold==0.104.1` against PyPI's vulnerability service found no known vulnerabilities on 2026-08-19.
- Nabu `projects/allies/engineering/guides/backend-development.md`: Django 6.0, Python 3.13, uv, and explicit app conventions.

## Decisions

- Use Unfold's default admin site integration; no custom `AdminSite`, dashboard, optional contrib apps, branding layer, or new admin URL is needed.
- Treat waitlist entries as operational records: expose an entirely read-only detail form to staff with explicit view permission, keep delete permission independent, give change permission no read or write effect, disable creation and saving, and keep durable digest fields out of the form.
- The product owner's explicit 2026-08-19 request creates and authorizes this separate task after the CLD-008 merge; the branch is based on current `dev`.
- Keep this as an internal fast-path Markdown work brief. The user's explicit request for Kickoff's first/fast path invokes Kickoff's narrow-task exception, which skips the otherwise paired Lavish HTML plan artifact and human approval gate; this file is a work brief with an embedded internal plan rather than a reusable full implementation plan.

## Risks

- A partial Unfold migration can leave individual model forms unstyled. Mitigation: convert and test every repository-owned admin class in the same change.
- Waitlist records contain personal content and security-sensitive digests. Mitigation: require explicit `view_waitlistentry` permission for the operator-relevant name, configuration, greeting/reply, email, consent, and timestamp fields; omit all attempt/completion digests; deny add/change mutations; and gate deletion separately.
- Unfold adds a third-party server-rendered template surface inside authenticated Django admin. Security assessment: release 0.104.1 is hash-locked, has no known advisory in the exact-pin `pip-audit` check, depends only on the already-owned Django boundary, and inherits Django template autoescaping plus staff/model-permission gates. Upstream released 0.104.1 on 2026-08-12 and documents Django 6.0/Python 3.13 support. Allies Cloud owns upgrades and should rerun compatibility, static-asset, and vulnerability checks when changing the minor-version cap.
- Admin list/search/detail reads and deletions expose or destroy personal content, while Django does not audit reads by default. Mitigation: emit timestamped, privacy-safe structured events after each successful list/search/detail view and single/bulk deletion using only public actor/entry references and a search-used boolean; never log the query or displayed content. Preserve Django admin's database-backed `LogEntry` deletion record as the durable deletion trail. Extend Django's default logging configuration and enable both existing Allies audit namespaces so the new channel neither replaces framework error/security logging nor leaves authentication audit events disabled.
- A dependency update can disturb the lockfile. Mitigation: constrain the current compatible minor release and run the locked uv validation suite.
- Rollback is a single PR revert; there is no migration or persisted-data transformation.

## Open Questions

- None blocking. Custom Allies branding and dashboard composition are explicitly out of scope.

## Plan

Internal fast-path plan:

1. Add focused failing admin tests that prove waitlist registration, the exact list/search/filter/ordering and read-only field contract, omitted digests, disabled add behavior, permission-gated list/detail/delete access, privacy-safe read auditing, all seven Unfold admin registrations, app ordering, and the unchanged `/admin/` route.
2. Add `django-unfold>=0.104.1,<0.105` through uv so `pyproject.toml` and `uv.lock` stay synchronized.
3. Put `unfold` before `django.contrib.admin`; migrate the auth and workspace admin classes to `unfold.admin.ModelAdmin`; register a read-only `WaitlistEntryAdmin` with the exact field and permission contract above.
4. Run `uv run pytest waitlist/tests/test_admin.py config/tests/test_admin.py`, `uv lock --check`, `uv run ruff format --check .`, `make lint`, `make check`, `uv run python manage.py migrate --noinput`, `uv run python manage.py migrate --check`, and `uv run pytest`.
5. Inspect the diff, run pre-PR review, commit with the required Codex co-author trailer, push, open a PR into `dev`, and monitor CI/review feedback.

Expected systems affected: `backend/pyproject.toml`, `backend/uv.lock`, `backend/config/settings.py`, repository-owned `admin.py` modules, and focused admin tests. No database schema, migration, external service, or public API changes.

## Execution Notes

- 2026-08-19: Kickoff selected the fast path because the cause and desired behavior are explicit, Unfold documents a minimal integration, rollback is straightforward, and validation is concrete.
- 2026-08-19: Adversarial review verdict was `Needs revision`. Accepted: define exact data/permission behavior and CI-equivalent tests. Resolved with fresher evidence: PR #8 is already merged and the user's instruction authorizes a separate task. Simplified: removed the proposed derived lifecycle state because no model-owned status exists. Rejected as conflicting with the explicitly requested Kickoff fast path: generating a Lavish HTML artifact for this internal brief.
- 2026-08-19: Simplicity review recommended only refreshing the dependency range. Accepted after direct PyPI JSON verification: use `django-unfold>=0.104.1,<0.105`. Protected complexity: default Unfold integration, seven migrated admin registrations, the read-only waitlist surface, and focused plus CI-equivalent validation.
- 2026-08-19: Isolated pre-PR review found one P1: `readonly_fields` alone still allowed an empty save that advanced `updated_at`. Accepted and fixed by denying change mutations while preserving explicit view-permission access; regression coverage verifies no save control, POST denial, and an unchanged audit timestamp.
- 2026-08-19: Final isolated review found no significant issues. Initial validation passed: 5 focused admin tests; 144 full-suite tests with 6 PostgreSQL-only skips; uv lock check; Ruff lint and format check; Django system and migration drift checks; migration apply/check; and production static asset collection.
- 2026-08-19: Enkii raised three P2s. Accepted: pin the exact detail-field tuple in tests, state the full personal-data surface accurately in this risk record, and require explicit view permission instead of overloading change permission as a read grant.
- 2026-08-19: Enkii's second pass cleared the original P2s and raised two more. Accepted: record the AL-11 dependency security assessment (exact-pin audit found no known vulnerability) and add privacy-safe structured audit events for successful waitlist list/search/detail reads.
- 2026-08-19: Enkii's final follow-up found that the first audit logger configuration could obscure Django's default framework/security handlers and did not cover deletion. Accepted: explicitly extend `DEFAULT_LOGGING`, then audit successful single and bulk deletions with the same PII-safe envelope.
- 2026-08-19: Enkii's next pass found that the new audit envelope could not independently establish when an event happened. Accepted: add a timezone-aware ISO 8601 timestamp, matching the repository's existing authentication-audit pattern.
- 2026-08-19: Enkii's next pass found that explicit logging enabled the new waitlist namespace but not the existing auth namespace, and questioned the durability of deletion events sent to the deployment log stream. Accepted: enable both Allies audit namespaces. Resolved with existing framework behavior plus regression evidence: Django admin writes a database-backed `LogEntry` before both single and bulk deletion, while the structured event remains the privacy-safe operational signal.
- 2026-08-19: Enkii's next pass identified brittle response and logger tests. Accepted: guard audit callbacks behind Django's template-response contract so a third-party response change does not take admin down, and verify logger output behavior without pinning handler count or private formatter attributes.
- 2026-08-19: Audit follow-up review found and fixed two issues before push: runtime INFO events needed an explicit logger/handler, and events needed post-render callbacks to avoid recording failed views as successful. Final isolated review found no significant issues. Validation passed: 8 focused tests; 147 full-suite tests with 6 PostgreSQL-only skips; lock, lint, format, Django, migration, and static-asset checks all green.
