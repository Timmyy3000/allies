# Hermes skill discovery and learning

Foundry profiles discover the image's read-only `/opt/allies/skills` catalog
through native `skills.external_dirs`. Hermes still owns `skills_list`,
`skill_view`, `skill_manage`, the Skills Hub CLI and background skill review.
There is no additional catalog service or user-facing catalog API in Foundry.

The pinned Hermes source supplies the catalog and support files. The four
proprietary office packages are excluded from the shared catalog; this does not
remove materials inherited elsewhere in the upstream image. Platform and
environment filtering remains Hermes' responsibility. X (`xurl`), GitHub and
email (`himalaya`) instructions are discoverable even when their executables or
account credentials still need setup. Discovery is not proof of account access.

The lightweight research, writing, diagram, maps and YouTube instructions use
the pinned image's existing tools. OCR instructions are discoverable, but a
local OCR engine is not preinstalled by this change. Account authorization,
paid services, desktop software and heavy dependencies are not enabled simply
by loading a skill. The discovery guide directs the Ally to check prerequisites
and explain any missing capability before promising execution.

Hermes' native readiness label checks declared skill metadata. The pinned OCR
skill declares no extractor requirement there, so its label is `available`
even without `pymupdf` or `marker`. The guide requires checking the instructions'
prerequisites; the smoke verifies these local extractors remain absent. This
change does not add a separate readiness model or rewrite the upstream skill.

## Additional skills

The existing terminal tool propagates the active Hermes profile to subprocesses.
The Ally can use native commands such as:

```sh
hermes skills search "research" --source official --limit 5 --json
hermes skills inspect official/category/skill-name
```

Use identifiers returned by search. Installation uses the existing Hub scanner
and profile-local destination. The Allies guide must not recommend `--force`
to bypass a rejected scan. Inspect prerequisites and license terms before an
installation; a search result is not an endorsement or working integration.

## Learned skills

Each profile retains its own writable `skills/` directory on the workspace
volume. The shared catalog is root-owned; improvements belong in a uniquely
named private skill, not an attempted edit of the image catalog. Existing local
skills take precedence in Hermes discovery, and native creation rejects name
collisions. Profile-scoped discovery does not expose another Ally's skills.
This is the native tool boundary, not a claim of OS-level isolation between
processes sharing a workspace.

Hermes can create or update a skill during work through `skill_manage`. Its
normal finalizer also schedules a best-effort skill review after the default
ten tool iterations when `skill_manage` is enabled and the turn has a final
response without interruption. The review may decide there is nothing useful
to save. This change neither lowers that threshold nor adds a learning worker
or scheduler. The image smoke uses deterministic model responses to exercise
the native path without requiring external model credentials.

## Existing profiles and rollout

Runtime materialization during generation reconciliation adds catalog configuration to existing
profiles. It preserves the manifest format, credentials, sessions, memories,
SOUL and learned skills. An existing valid custom skills block already pointing
at the catalog is left byte-for-byte intact. Ambiguous or unsupported custom
configuration returns `skills_config_requires_repair`; the original file is
retained for inspection rather than silently rewritten.

After review and merge, publish **both** the Hermes image (catalog) and runtime
image (profile configuration and parser) through their existing workflows.
Set the resulting immutable image pair together through the existing deployment
process. Existing sleeping workspaces receive the pair through release-on-wake
reconciliation. A fresh profile and an existing-profile canary must both show
catalog discovery before broader rollout is considered verified.

Rollback uses the previous image pair. Manifest version 2 and private skill
files remain compatible. An older Hermes image can ignore the unavailable
external directory. No package downloads or Hub searches run during wake-up.
