---
name: create-pr
description: Prepare and create a pull request from the current branch. Use when the user asks to create a PR, open a pull request, prepare a branch for review, or ship changes through PR. Run project validations, invoke $code-review, triage P0-P2 findings, fix blocking bugs, rerun checks, push the branch, and create a standardized PR with summary, scope, tests, test plan, and local review findings.
---

# Create PR

Prepare a branch for review and create the PR only after local validation and blocking local review findings are clean.

## Operating Rules

- Work on the current branch unless the user explicitly asks to switch.
- Do not create a PR from `main`, `master`, `dev`, `staging`, or `prod` unless repo guidance explicitly allows it or the user confirms.
- Preserve unrelated user changes. Do not stage, commit, or rewrite files outside the PR work.
- Follow project guidance before inferred defaults. Read `AGENTS.md`, `.cursor/rules/*`, `CONTRIBUTING.md`, package config, Makefiles, CI workflow files, and repo-specific docs relevant to changed paths.
- If validation commands fail because of unrelated pre-existing repository state, stop and report the blocker instead of hiding it.
- Automatically create the PR after all required checks pass and P0/P1 local review findings are fixed or explicitly deferred by the user.
- When this skill is part of an end-to-end workflow, return enough PR context for the caller to start or update a 5-minute review monitor immediately.

## Workflow

1. Create and maintain a short todo list.
2. Identify repo root, current branch, base branch, remote, changed files, uncommitted changes, and whether the branch has commits to push.
3. Load project guidance and discover validation commands.
4. Run local validations before review.
5. Invoke `$code-review` on the branch diff.
6. Triage review findings by priority.
7. Fix blocking findings that are clear, scoped, and safe to fix.
8. Rerun the smallest meaningful validation after each fix batch.
9. Rerun `$code-review` if fixes touch risky logic or previous P0-P2 findings.
10. Commit local fixes with the repo's commit conventions.
11. Push the branch.
12. Create the PR with the standardized body.
13. Report PR monitoring context to the caller.

## Validation Discovery

Use documented commands first. If no guidance exists, infer commands conservatively from repo files:

- JavaScript or TypeScript: inspect `package.json` scripts and run available lint, typecheck, and test commands. Respect the repo's package manager lockfile.
- Python: inspect `pyproject.toml`, `pytest.ini`, `Makefile`, and docs. Run format/check commands and targeted tests where available.
- Go: run `go test ./...`.
- Mixed repos: run the smallest meaningful commands for touched areas first, then broader checks if the blast radius is high.

For Docsyde backend changes, treat `make format` as a blocking validation step and verify touched backend code reaches the repo's required local coverage target when applicable.

Record each command, whether it passed, and the relevant output summary for the PR body.

## Local Review Triage

Classify `$code-review` findings:

- `P0`: critical correctness, security, data loss, tenant isolation, or production-breaking issue. Must fix before PR.
- `P1`: high-confidence bug, regression, or required project-guidance violation. Must fix before PR.
- `P2`: meaningful edge case, missing risky test, or maintainability issue likely to matter. Fix by default unless clearly out of scope or user defers.
- `P3`: nit, small cleanup, or low-risk improvement. Do not block PR by default.

For each P0-P2 finding, list priority, file and line, issue summary, proposed fix, and status: fixed, deferred with reason, or needs user decision.

Ask before broad rewrites, product behavior changes, schema changes, migrations, destructive operations, or fixes that expand scope beyond the PR.

## Fix And Commit

- Keep fixes narrow and directly tied to validation or local review findings.
- Rerun targeted tests after fixes.
- If backend formatting rewrites files, rerun the smallest meaningful backend test suite.
- Commit only the intended PR files. Include the required agent co-author trailer when project guidance requires it.

## PR Creation

Use `gh pr create` when available. Target the detected base branch unless project guidance or the user says otherwise.

Create the PR after:

- required validations pass,
- P0/P1 findings are fixed or explicitly deferred,
- P2 findings are fixed or documented with a defensible deferral,
- branch commits are pushed.

Use this PR body:

```markdown
## Summary

{Brief explanation of the change.}

## What's Included

- {Main change 1}
- {Main change 2}

## Tests

- `{command}`: {passed/failed/not run with reason}

## Test Plan

- {Manual or scenario-based checks performed}
- {Important flows verified}

## Local Review Findings

- P0: {none / fixed / deferred with reason}
- P1: {none / fixed / deferred with reason}
- P2: {none / fixed / deferred with reason}
```

If the repository has a required PR template, preserve its required sections and merge these fields into it.

## PR Monitoring Context

After creating the PR, report:

- PR URL.
- PR number when available.
- Head branch.
- Base branch.
- Remote.
- Current check/CI status when discoverable.
- Whether a code review bot appears to be active or pending.
- Any immediate review, mergeability, or authentication blockers.

If `create-pr` is invoked by `ship-it` or another end-to-end workflow, explicitly hand back: `Start or update a 5-minute PR monitor now.`

If `create-pr` is invoked standalone and automation tools are available, create or update the 5-minute PR monitor directly. If automation tools are unavailable, tell the user that the PR was created but no monitor could be scheduled.

## Stop Conditions

Stop before creating the PR when:

- required checks fail after attempted fixes,
- unresolved P0/P1 findings remain without explicit user deferral,
- the branch has unrelated staged changes,
- the base branch cannot be determined safely,
- authentication or remote push fails.
