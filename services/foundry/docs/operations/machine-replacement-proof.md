# Machine replacement continuity proof

Use this runbook to execute FND-008 against Fly. The command creates one test
workspace and runs two isolated conversations. It replaces the Machine while
two streams are active, checks the generation fence and session continuity,
then removes the proof resources.

The command has no fake mode. Local deterministic coverage runs through the
service test suite.

## Before you run it

Confirm all of the following:

- `fly.exe auth whoami` succeeds with access to the target organization.
- The runtime image is published by immutable digest and contains the FND-008
  worker entrypoint.
- Foundry is deployed at a public HTTPS origin that Fly Machines can reach.
- Fly multi-container Machines and runtime-container file secrets are available
  for the target account.
- You have an OpenAI API key with access to `gpt-5.6-luna`.
- The evidence output file does not already exist. Its parent directory must be
  writable.

Set the two capability gates for the current terminal:

```powershell
$env:FLY_MULTI_CONTAINER_ENABLED = "1"
$env:FLY_FILE_SECRETS_ENABLED = "1"
```

These flags are assertions about capabilities you have verified. They do not
enable a Fly feature by themselves.

## Runtime image migration

FND-008 intentionally changes the runtime image's default command. Earlier
images started the passive Hermes readiness process (`python -m allies_runtime
--serve`). The new default starts the Foundry worker (`python -m
allies_runtime`) and exits if its required runtime configuration is absent.

Before deploying the new image to an existing Machine, choose one path:

- To activate the Foundry worker, supply `HERMES_CREDENTIAL_REF`,
  `FOUNDRY_ORIGIN`, and `FOUNDRY_RUNTIME_CREDENTIAL_REF`, mount the referenced
  Foundry bearer beneath `/run/secrets`, and confirm Hermes is reachable with
  the configured credential resolver.
- To preserve the legacy passive behavior temporarily, override the runtime
  container command with `python -m allies_runtime --serve`. This compatibility
  mode probes Hermes and remains available, but it does not claim or execute
  Foundry work.

Do not update an existing deployment to the new image without either the worker
configuration or the explicit `--serve` override. Otherwise the runtime
container will fail closed during startup.

## Save the OpenAI key locally

Create a file outside the repository that contains only the OpenAI API key. Do
not add quotes or an environment-variable name. A trailing newline is fine.

For example, save it here:

```text
C:\Users\ASUS\AppData\Local\Allies\proof-secrets\openai-api-key
```

Do not paste the key into the command, chat, evidence file, or repository. The
proof command reads the file locally and sends the key to Fly through standard
input. Fly mounts it only in the runtime container at
`/run/secrets/openai-api-key`.

## Run the proof

Replace the remaining angle-bracket values. Keep the OpenAI key file outside
the repository.

```powershell
Set-Location backend

uv run --locked python manage.py prove_machine_continuity `
  --live `
  --runtime-image "<registry/runtime@sha256:digest>" `
  --foundry-origin "https://<foundry-host>" `
  --provider-api-key-file "C:\Users\ASUS\AppData\Local\Allies\proof-secrets\openai-api-key" `
  --model "gpt-5.6-luna" `
  --organization "<fly-organization>" `
  --region "ams" `
  --output "<absolute-path>/fnd-008-evidence.json"
```

The command generates the Hermes API key and each Machine generation's Foundry
bearer. It sends all secret values to Fly through standard input. The runtime
container receives the OpenAI key, Hermes key, and Foundry bearer as separate
files. The Hermes container receives only the Hermes key file. Its proof
startup command reads that file into `API_SERVER_KEY` before starting
`hermes gateway run --no-supervise`. No raw secret is written to the evidence
file or Machine configuration.

Cleanup removes the temporary Fly secrets along with the proof Machine, Volume,
and App. Keep the local OpenAI key file if you plan to rerun the proof, or remove
it yourself after the proof passes.

## Interpret the result

The command always writes sanitized JSON when the output path is valid.

| Exit | Status | Meaning |
| ---: | --- | --- |
| `0` | `pass` | Every required continuity check passed and cleanup completed. |
| `1` | `fail` | The proof mutated resources and a required check failed. |
| `2` | `skipped` | Preflight failed before provider mutation. |
| `3` | `incomplete_cleanup` | Cleanup failed. This takes precedence over proof failures. |

A passing report must show:

- generation 1 and generation 2 Machine IDs with one stable Volume ID;
- two proof-held generation 1 executions fenced without replay;
- the same-profile queued turn starting only on generation 2;
- both profiles reconciled and resumed on generation 2;
- isolated session continuity for Ally A and Ally B;
- `cleanup: complete`.

## Failure and rerun

Do not rerun with the same output path. Read the final check's safe detail code,
verify cleanup, correct the failing prerequisite, and choose a new output file.

For `incomplete_cleanup`, inspect the owned App named in `resources.app` before
removing anything. Delete only IDs recorded in the evidence. Do not use a broad
organization cleanup command.

After a passing live run, retain the sanitized evidence and recording in the
approved project location, then update Nabu with the result and the Milestone 2
estimate. Raw terminal logs are not committed by default.
