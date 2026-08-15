---
name: code-review
description: Pre-PR code review for local branch changes. Use when the user asks to review changes before a PR, check the current branch, inspect a diff for issues, or run a code review. Analyze the branch diff against its base for correctness bugs, failure modes, security risks, project-guideline violations, regressions, and missing tests. Report only actionable findings with file and line references.
---

# Code Review

Review local branch changes before a pull request. Prioritize real correctness, security, reliability, and maintainability issues over style preferences.

## Workflow

1. Create a short todo list for the review.
2. Identify the current branch, base branch, changed files, diff stats, and commits being reviewed.
3. Stop early if there are no changes to review or the branch is the same as the base branch.
4. Check for uncommitted changes and state whether they are included in the review.
5. Load relevant project guidance files before reviewing. Prefer files such as `AGENTS.md`, `.cursor/rules/*`, `CONTRIBUTING.md`, repo-specific agent guides, or guidance files near changed paths.
6. Prefer an isolated first-pass review by spawning a separate child agent before doing any main-thread review synthesis. Give that child agent the branch name, base branch, diff stat, changed files, commits, relevant guidance, PR title/body if available, and the branch diff or a way to inspect it. Do not fork the full conversation context unless the review would otherwise lack required facts. The goal is to reduce bias from earlier discussion and implementation context.
7. Have the child agent run this same `$code-review` workflow against the branch diff and return only actionable findings with file and line references plus a brief note if no significant issues were found.
8. Review only changes introduced by the branch. Use surrounding and related code as context, but do not flag unrelated pre-existing problems.
9. Perform the review passes below. The main agent should use the isolated child-agent output as the starting point, then do any targeted follow-up checks needed to confirm or dismiss findings.
10. Score candidate findings with the confidence rubric.
11. Report findings with confidence score >= 70. If none meet the threshold, say no significant issues were found and mention the main areas checked.

## Review Passes

### Project Guidance Compliance

- Verify changed code follows relevant project instructions.
- Only flag violations that are specific and applicable to the changed files.
- Cite the guidance file when it directly supports a finding.

### Bug And Logic Scan

- Check typos, wrong variables, missing returns, copy-paste errors, and inverted conditions.
- Trace conditionals and loops with concrete inputs.
- For state machines, parsers, regexes, migrations, serializers, auth flows, and data transformations, verify downstream assumptions match produced values.
- For regex or parser changes, test at least a happy path, an edge case, and malformed input.

### Failure Mode Analysis

- Check async rejection handling, timeouts, retries, unexpected responses, null values, empty collections, malformed data, and boundary values.
- Check resource acquisition and release paths.
- Ask what input or environment condition would break the changed code.

### Related Code And History

- Inspect sibling files and existing patterns that the change should match.
- Use `git blame` and recent file history when historical context could explain an invariant or regression.
- Check whether behavior expected by callers, tests, routes, workers, or UI consumers changed accidentally.

### Comment And Documentation Compliance

- Read comments, TODOs, FIXMEs, docs, and type/interface contracts near changed code.
- Flag changed behavior that contradicts nearby documented expectations.

### Test Coverage Gaps

- Check whether new paths, branches, edge cases, error paths, and parsing variations have meaningful tests.
- Flag missing tests when the untested behavior is risky or likely to regress.

## Confidence Rubric

Score each candidate finding from 0 to 100:

- `0`: Not confident. Likely false positive, pre-existing issue, or unsupported by evidence.
- `25`: Somewhat confident. Plausible but not verified, or mostly stylistic without project guidance.
- `50`: Moderately confident. Real issue, but low impact, rare, or partially speculative.
- `75`: Highly confident. Verified likely issue that can be hit in practice and should be fixed.
- `100`: Certain. Direct evidence confirms a frequent or severe issue.

For project-guidance findings, verify the cited guidance actually requires the behavior.

## Do Not Flag

- Pre-existing issues not introduced by the reviewed branch.
- Issues on unrelated lines unless the branch makes them newly reachable.
- Findings already caught trivially by formatters, linters, typecheckers, or compilers.
- General style preferences unless explicitly required by project guidance.
- Intentional behavior changes that match the broader change.
- Suppressed lint warnings when the suppression is intentional and allowed by project guidance.

## Flag Even If Small

- Unhandled async errors or promise rejections.
- Missing guards for null, undefined, empty, malformed, or boundary inputs.
- Incorrect parser or regex capture group usage.
- Resource leaks on error paths.
- Security regressions in auth, permissions, secrets, validation, redirects, uploads, injection boundaries, or tenant isolation.
- Missing tests for risky new branches or error paths.

## Report Format

Lead with findings ordered by severity. Include branch, base, changed file count, issue location, reason, and suggested fix. Use short snippets only when they make a finding clearer.

If no issues meet the threshold, report that no significant issues were found and list the main areas checked.

## Isolation Preference

- Default to a child-agent first pass whenever delegation is available and the user has not asked to avoid subagents.
- Seed that child agent with review inputs, not the whole implementation conversation.
- Preferred inputs: branch name, base branch, commit list, changed files, diff stat, PR title/body, relevant guidance files, and the diff itself or commands to inspect it.
- If a fully isolated pass is not possible, state that clearly in the review output and proceed with the best local review available.
