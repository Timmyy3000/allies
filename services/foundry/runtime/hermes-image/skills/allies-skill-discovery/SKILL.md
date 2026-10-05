---
name: allies-skill-discovery
description: Find shared Hermes skills, check setup, and create private adaptations.
version: 1.0.0
author: Allies
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [skills, discovery, setup, learning, allies]
---

# Allies Skill Discovery

Use Hermes' native skill tools for progressive disclosure:

- Call `skills_list` to see the shared and profile-local skills.
- Call `skill_view(name="...")` for a skill's instructions. Use
  `skill_view(name="...", file_path="references/...")` for support files.
- Use the absolute `skill_dir` returned by `skill_view` for scripts and assets;
  shared skills may live outside the profile's local skills directory.
- Check a skill's prerequisites before claiming that it is ready. A missing
  command, credential, or optional service is `setup needed`; explain the
  setup the skill requests and continue only when it is available.
- A native `available` status checks declared metadata, not every dependency
  mentioned in a skill. Local OCR, for example, still needs an extractor even
  if its skill reports available. Read and check the relevant prerequisites.

## Missing executables

The image includes `xurl`. Verify with `command -v xurl` and `xurl --help`;
account authentication is separate. Follow the xurl skill's secret-handling
instructions and never print credential files or request secrets in chat.
Do not run `xurl token` or verbose requests; use `xurl auth status` for setup checks.

For another missing executable, inspect the skill's installation instructions
and supported operating systems. Use the existing terminal to install a
task-required dependency from its official source, choosing a concrete version.
Verify the registry package matches the official project and review its license.
Keep tools in a writable directory under the active profile's persistent
`HERMES_HOME`, not the sealed Hermes environment or a temporary directory.
For npm tools, use `npm install --ignore-scripts --prefix <persistent-tool-directory>
<package>@<version>` and invoke its `node_modules/.bin/<command>` directly.
For Python tools, use `UV_TOOL_DIR=<persistent-tool-directory>
UV_TOOL_BIN_DIR=<persistent-bin-directory> uv tool install --no-build <package>==<version>`
and invoke the installed executable by absolute path. Save that invocation in
a private skill so later conversations can reuse it without relying on PATH.

Verify `--help` or the documented version command before using a new tool.
Do not use sudo, change shared packages, bypass the skill scanner, or install
dependencies on every wake. Packages requiring install scripts or source builds
need image/deployment review; do not retry with those protections disabled.
If installation needs system libraries, an
unsupported OS, a GPU, or an external service, report that specific prerequisite.
Installing a program does not connect the user's account or authorize actions.

Search the official Hermes Hub from the existing terminal CLI when a shared
skill is not present:

```bash
hermes skills search "QUERY" --source official --json
hermes skills inspect IDENTIFIER
hermes skills install IDENTIFIER
```

Hub search and installation may require network access or credentials. Report
those prerequisites honestly; profile wake does not download skills.
Use an identifier returned by search, review its prerequisites and license,
and keep the native installation scanner enabled. Do not bypass a rejected
scan with `--force`.

When a shared skill needs an Allies-specific adaptation, create a uniquely
named private skill with `skill_manage(action="create", name="...")`. Keep the
name distinct from the shared skill and do not edit a skill under
`skills.external_dirs`. Private learned skills live in this profile's writable
`skills/` directory and remain available after a restart.
