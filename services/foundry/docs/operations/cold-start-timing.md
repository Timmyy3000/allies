# Cold-start timing runbook

Use this runbook to compare Foundry cold-path phases and the optional Fly
bootstrap-helper candidate. Keep provider names, resource IDs, credentials,
customer identifiers, and raw logs in a private evidence directory outside the
repository.

## Capture a run

Run the same revision, immutable runtime image, region, machine shape, and
feature flags for every control and candidate sample. Keep the pool and all
optional wake or hint senders disabled while measuring the cold path. The live
Fly proof owner supplies the provider configuration; this runbook does not
contain application IDs or credentials.

Enable complete, privacy-safe phase events for a local run:

```powershell
$env:ALLIES_WIDE_EVENTS_ENABLED = "true"
$env:ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE = "1"
$env:ALLIES_WIDE_EVENTS_SINK_ENABLED = "false"
```

Capture the process's structured stdout to a file outside the repository while
running the existing cold-path command or harness. Keep the command's own
sanitized evidence beside that log. Do not add secrets or request content to
either file.

The phase events use the `runtime.operation.*` schema. Useful Foundry phases
include:

- `proof.provider_preflight`, `proof.app`, and `proof.release_bootstrap`;
- `proof.dependency_credential_stage`, `proof.runtime_credential_stage`,
  `proof.runtime_credential_issue`, and `proof.secret_deploy`;
- `workspace.provision.app`, `.volume`, `.machine_create`, `.machine_start`,
  `.machine_health`, `.activation_gate`, and `.bind`;
- `workspace.replace.*` for replacement measurements;
- `activation.*` for the activation command path.

Each completed or failed phase includes a bounded `duration_ms`. A started
event marks the phase boundary; pair it with the same `operation` and the next
completed or failed event. Provider and workspace references are emitted only
through the observability sanitizer.

## Compare controls and candidate

Collect at least three control and three candidate samples for each image
state. Record the revision, image digest, region, topology, feature flags, run
kind, and sanitized phase samples in the private evidence bundle. Report every
sample and the median; keep first token and completed reply as separate
measurements when the harness reaches the runtime.

The candidate helper configuration is deliberately narrow:

```toml
kill_signal = "SIGTERM"
kill_timeout = "5s"

[experimental]
entrypoint = ["/bin/sleep", "1800"]
```

These settings apply to the unused release/bootstrap helper. The proof must
still read the release metadata, match the expected release ID and version,
and stop exactly the recorded helper Machine. Application Machine startup,
credential ordering, readiness checks, ownership checks, and shutdown remain
on the existing path. Do not remove inherited image files or change Hermes,
tool, model, or runtime capabilities as part of this measurement.

Compare the `proof.release_bootstrap` span and the full cold timeline. Claim a
bootstrap improvement only when the candidate is faster across repeated
matched samples and the staged-release, ownership, cleanup, health, first-token,
and completion checks remain unchanged. A neutral or unsupported candidate
keeps the phase instrumentation and uses the prior helper behavior.

Retain the current shell-wrapper stop observation (about six seconds from
interruption to exit) as the baseline for the candidate comparison. Measure the
actual helper Machine stop in each run; a configuration value alone is not a
speed result.

## Cleanup and evidence

After each run, verify the command's sanitized cleanup result. Inspect only
provider resources recorded by that run and retain assigned resources according
to the proof policy. Never use organization-wide name-pattern deletion.

Keep the private evidence bundle outside the repository. A reviewable summary
should contain:

- matched control and candidate inputs;
- individual and median phase durations;
- first-token and completion timings;
- release, ownership, secret-order, and cleanup checks;
- the reason for accepting, omitting, or reverting the candidate.
