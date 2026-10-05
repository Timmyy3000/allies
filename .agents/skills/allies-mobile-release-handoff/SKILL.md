---
name: allies-mobile-release-handoff
description: Release Allies mobile changes with the correct OTA or native APK path, synchronized README and Nabu handoff records, verified Git commits, and EAS release metadata.
---

# Allies Mobile Release Handoff

Use this skill when a mobile implementation is ready to be handed off, committed,
published through EAS Update, or packaged into an Android preview build. It is for
the Allies repository and its mobile release records; it does not replace product
specifications, code review, or feature implementation.

## Non-negotiable project context

- Work from the repository root and read the applicable `AGENTS.md` files before
  changing anything. Read `ENGINEERING_STYLE.md` and `apps/mobile/README.md` before
  choosing release metadata or commands.
- Read the canonical Allies index and the mobile onboarding handoff in Nabu before
  changing release records. Use the repository's Nabu skill and native MCP tools;
  never place Nabu credentials, bearer tokens, cookies, or invite URLs in files,
  logs, commits, or chat.
- Preserve unrelated worktree changes. Stage only the intended implementation and
  release-documentation files.
- Commit material agent help with `Co-authored-by: Codex <codex@openai.com>` and do
  not push `main` or `dev` directly. Use the current authorized mobile branch.
- README and Nabu are release-handoff records. Update them at meaningful commit or
  release boundaries, not after every exploratory edit.

## Release decision

Classify the change before publishing anything:

| Change | Required delivery |
| --- | --- |
| JavaScript, styling, animation, or already-bundled asset changes only | Commit and push, then publish an EAS Update to the matching channel/runtime when the user has authorized publication. |
| Native dependency, Expo/React Native upgrade, plugin, splash screen, Android configuration, permission, scheme, native code, or runtime/app-version change | Bump `expo.version` deliberately, resolve the public Expo config, commit and push, then create a new EAS build. Do not send an incompatible OTA to an older binary. |

For native changes, use the exact Expo SDK documentation required by the nested
mobile repository instructions before changing native configuration. A splash-screen
plugin change is native and requires a new APK; an OTA cannot replace it in an
already-installed binary.

Do not infer permission to publish an OTA, create a build, commit, or push from a
request that only asks for a code change. Proceed automatically only when the current
request clearly authorizes the release action. If a release is authorized, do not
stop for routine confirmation prompts; stop only for a real missing credential,
conflicting worktree, failed validation, or a material scope decision.

## Required workflow

### 1. Verify the implementation

Inspect the diff and confirm the README describes the behavior that is actually in
the code. Run the smallest relevant checks after each meaningful phase, then run the
complete mobile-relevant validation before handoff. For this repository, that normally
includes:

```text
bun run test:run
bun --filter mobile lint
bun --filter mobile typecheck
git diff --check
```

Record the exact test-file/test counts and command results. Never claim a check passed
unless it ran successfully. If validation fails, diagnose and fix the failure before
release; do not hide it in the handoff.

### 2. Update the mobile README with the code

Before the implementation commit, update `apps/mobile/README.md` with only facts
verified from the current code and EAS state. Keep these sections accurate when they
apply:

- current app/package/runtime versions and Android application ID;
- whether the next delivery is OTA or a native build;
- user-visible behavior, motion, assets, and important implementation boundaries;
- exact validation evidence;
- release history entry with date, change summary, branch, and intended delivery;
- for an existing release: commit SHA, EAS channel/environment, update group or
  build ID, Android build number, runtime, and artifact URL;
- the device-owner action still required, including whether installation or restart
  is needed.

Do not mark a build as finished or publish an artifact URL before EAS reports it.

### 3. Commit and push the code boundary

Review `git status`, the staged diff, and `git diff --cached --check`. Stage only the
intended files. Use a focused commit with the required Codex co-author trailer, then
push the authorized mobile branch. Capture the full commit SHA because EAS and Nabu
records should point to an immutable commit, not a moving branch name.

### 4. Synchronize Nabu revision-safely

After the code/README commit is pushed:

1. Read `projects/allies/engineering/specs/interface/mobile-onboarding-implementation.md`
   again and capture its current revision.
2. Preserve its complete frontmatter and raw Markdown. Merge the new release facts
   into the existing note; do not replace or shorten unrelated sections.
3. Update with exactly one `rawMarkdown` or structured document and the
   `expectedRevision`.
4. Re-read the canonical path and verify the commit, behavior, validation, and
   release status are present.

If the revision is stale, re-read, merge against the newer content, and retry. If
Nabu is unreachable, do not fabricate a successful sync. For a safe implementation,
add a dated `Nabu sync pending` entry to the README with the local sources checked,
the unavailable note, the changes made, and the reconciliation required later.

### 5. Deliver through EAS

For an authorized OTA-only release, run from `apps/mobile`:

```text
bunx eas-cli update --channel preview --environment preview --message "Describe the ready batch"
```

Use the channel and environment matching the installed binary. Publish only from a
committed, pushed worktree. After EAS returns, capture the update group ID and any
platform update ID, then update the README and Nabu release records and verify both.

For an authorized native preview release, run:

```text
bunx eas-cli build --platform android --profile preview
```

Wait for or poll the remote build until it is `FINISHED` or has a concrete failure.
Record the build ID, app version, runtime version, Android build number, immutable
commit SHA, and installable artifact URL. Then update the README with the finished
artifact, commit and push that release-record change, and update Nabu revision-safely
with the final build facts. A native build should not be described as ready while it
is queued or compiling.

If a build fails, preserve the build ID and error details in the working status, fix
the cause, rerun the relevant checks, and create a new build rather than presenting a
failed artifact as installable.

## Handoff checklist

Before reporting completion, verify:

- The implementation is committed on the intended mobile branch.
- The README is committed and pushed with accurate version/release information.
- Nabu was read before mutation, updated with the expected revision, and re-read.
- The delivery type matches the runtime boundary: OTA for JS-only changes, APK for
  native changes.
- EAS status and artifact metadata are verified directly.
- Validation results are stated with evidence.
- The final response links the APK or explains the OTA command/device action, and
  explicitly notes any preserved unrelated untracked files or remaining blocker.
