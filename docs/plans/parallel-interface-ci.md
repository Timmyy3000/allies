# Parallel Interface CI

Status: implementation for PR review; owner requested faster CI without increased compute cost.
Route: fast; workflow-only change, no HTML needed.

## Scope and approach
Split the existing serial job into two independent lanes on the same 2-vCPU runner class. Checks owns contract validation, types, unit/component tests, lint and scoped iOS export. Web owns the single production web build, browser installation, Home, motion and chat-frame checks plus their existing evidence. Each lane evaluates the existing trusted-base scope selector. No suite is removed, no retry/worker count increases, no duplicated build or build artifact transfer.

Keep the required Interface CI suite name as a final always-running gate. Require both lane results to be successful and both checked source SHAs to match before exporting source_sha to promotion callers. A moving branch ref must fail closed rather than promote a partially tested revision.

## Acceptance and validation
- Preserve every prior validation/evidence step, event trigger, scope condition and reusable source_sha output.
- Check YAML and GitHub expressions with actionlint; exercise gate success, failed/canceled/skipped lane and mismatched SHA cases.
- Run existing ci-scope tests. Review correctness and simplicity separately.
- Observe the full-scope PR run. Compare elapsed time and sum of runner minutes with a successful full-scope baseline; runner minutes are a cost proxy, not billing proof.

## Cost, rollout and rollback
Two lane setups plus a tiny gate add overhead. No claim of cost neutrality until measured; simultaneous progress can waste more work on failing runs. Keep the PR unmerged if comparable successful runs show increased total runner minutes, and adjust grouping or revert. No larger runners, browser worker increases or extra benchmark reruns. Rollback is reverting this workflow change. Existing promotions still require the final validation gate.

## Local validation and review
- `bun x vitest run scripts/ci-scope.test.ts`: 13 passed.
- `actionlint -ignore 'label "blacksmith-2vcpu-ubuntu-2404" is unknown' .github/workflows/ci.yml`: passed (only the existing custom runner label exempted).
- Executed the actual gate Bash with seven result/SHA combinations: success exports the SHA; failed, canceled, skipped, mismatched and empty inputs fail without output.
- Compared old and new workflows: all 11 validation steps remain exactly once.
- Correctness review: reusable output and required-check name preserved; both lane SHAs must agree; failed or skipped dependencies cannot produce a green gate. Existing scope selector still uses trusted base code.
- Simplicity review: two execution lanes, one minimal gate; no composite action, matrix, copied build artifact, added cache, extra test runner or larger machine.
- CI timing and total runner-minute comparison remain pending. This PR is not yet demonstrated cost-neutral and must not auto-merge on functional success alone.

## Owner-added invite feedback scope
The owner explicitly requested this fix in the same open PR61. Preserve the allowlisted invite_required callback error when /home redirects signed-out users to the landing page. Show the existing notification style with clear beta-invite copy, a claim link and dismissal; clear the URL error on dismissal. No backend authentication changes, account creation or new sign-in screen. Ordinary signed-out redirects now go directly home. Production-build browser tests cover both redirects, toast/link, dismissal and reload; two passed. Seven focused redirect component tests, typecheck/build and scoped lint pass. Correctness review: only a literal allowlisted error is forwarded, no raw callback text or external redirect; dismissal preserves other URL components. Simplicity review: one local notice component, existing CSS, no new toast dependency or API.
