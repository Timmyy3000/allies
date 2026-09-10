# Hermes capabilities and setup

Inspected against the pinned Hermes source `36cb5ae5530a75def7df3195e49b7a4aa2add482`.
Skill discovery, executable installation and account access are separate checks.
Do not report a skill as usable merely because `skills_list` returns it.

| Capability | Current boundary |
| --- | --- |
| Mnemosyne | Managed profiles use the reviewed memory tools. Profile isolation, retention validation, 4 KiB records, a 64 MiB database cap and schema validation remain enforced. Automatic transcript capture, consolidation, embeddings and shared memory are not enabled. Raw transcripts, inferred facts and transient results are rejected; durable memory is distinct from run history. |
| Skills | Eligible MIT catalog and writable private skills are available, including native Hub discovery and background skill learning. The proprietary docx/xlsx/pdf/powerpoint skill packages are excluded from the shared catalog for licensing; this is not a ban on producing those file formats. |
| X | The image includes checksum-pinned xurl 1.3.1. X account/API access must still be configured separately using the skill's credential-safe flow. An installed CLI does not prove an authenticated request works. |
| Other CLI skills | The inspected base has no gh, Himalaya, Tesseract or Go executable. Python and Node package tools, curl, Git and ffmpeg are present. Install task-required optional tools into persistent profile storage through the native terminal; use the discovery skill's guidance. |
| OCR and documents | The catalog includes instructions/scripts, but local PyMuPDF and Marker extractors are absent from the baseline. These require dependencies; discovery metadata alone does not detect them. |
| Native cron | Disabled in Allies API turns. The Cloud-backed routines tool replaces it so sleeping machines do not own the schedule. Routine runs cannot manage schedules recursively. |
| Terminal, files, browser, code execution, delegation, history | Included in the pinned API default toolsets. Actual tools can still be gated by provider credentials, executable availability and profile configuration. No new broad restriction is added here. |
| Desktop GUI and macOS skills | A Linux server cannot provide Apple Notes, iMessage, Find My or a user's desktop by exposing their instructions. They need a compatible connected host. Hermes desktop-only UI tools are gated upstream. |
| External integrations and media | Search, image/video/audio generation, Spotify, Home Assistant and similar integrations depend on providers, credentials or services. Upstream also defaults several optional toolsets off. A catalog entry does not supply those connections. |

For each requested skill, check its instructions and prerequisites, then the actual
executable (`command -v` and documented help/version command), then account/service
readiness using a non-secret status command. Do not print credentials to diagnose
setup. Some prerequisites are only mentioned in prose, not machine-readable metadata.

Use a pinned official release for a frequently used executable in the image.
Use native uv/npm or the official package mechanism for less common dependencies,
with installation directories under the active profile's persistent HERMES_HOME.
Verify official package identity and license; disable npm install scripts and
require Python wheels. Source builds or lifecycle scripts need deployment review.
Invoke these tools by absolute path and retain the invocation in a private skill.
Do not change the sealed Hermes environment or install packages on every wake.
System libraries, GPU services and incompatible operating systems need deployment
work, not repeated install attempts by the Ally.

Publish the Hermes/runtime image pair after merge and allow managed profile
reconciliation before testing an existing Ally. Confirm a real remember/recall
across conversations and a credentialed X read separately from image smoke checks.
