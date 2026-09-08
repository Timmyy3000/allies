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
