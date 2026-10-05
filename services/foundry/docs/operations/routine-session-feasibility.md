# CLD-012 routine-session feasibility evidence

This note records the bounded feasibility commands and their current evidence
status. It does not claim product behavior, concurrent Foundry admission, or a
successful Hermes capability proof.

## Pins

- Hermes source revision: `36cb5ae5530a75def7df3195e49b7a4aa2add482`
  (`runtime/hermes-image/Dockerfile`).
- Class A image reference: `allies/hermes-mnemosyne:dev`; observed image ID
  prefix: `sha256:4127ae957bc3d`.
- Class B image input: a required local `image@sha256:<64-hex-digest>` resolved
  from the pinned source revision. No digest was verified.
- Model required by the probe: `gpt-5.6-luna`.

## Class A — offline provider/storage diagnostics

Exact command:

```powershell
docker run --rm --network none --entrypoint /opt/hermes/.venv/bin/python --mount "type=bind,source=$PWD/runtime/hermes-image/smoke_routine_sessions.py,target=/tmp/smoke_routine_sessions.py,readonly" allies/hermes-mnemosyne:dev /tmp/smoke_routine_sessions.py --mode offline --timeout-seconds 60
```

Status: **INCONCLUSIVE_REVIEW_REQUIRED** for the aggregate Class A claim.
The pinned probe was repeated three times against image ID prefix
`sha256:4127ae957bc3d` from source commit
`36cb5ae5530a75def7df3195e49b7a4aa2add482`: one run returned
`OFFLINE_DIAGNOSTICS_FAILED` because distinct-session concurrent
`mnemosyne_remember` produced the sanitized `bad parameter or other API misuse`
response; two subsequent runs returned `CLASS_A_PASSED`.

Per-property evidence remains: provider readiness, profile-keying, shared
surface disabling, context-only tool suppression, SQLite timeout, profile
storage isolation, sequential writes, fresh same-profile recall, and the
isolated-profile negative check passed. Concurrent distinct-session writes are
intermittent, so aggregate concurrent-write capability is not proven safe and
Class A overall is not marked passed.

This is provider/runtime remediation input for FND-012, not a CLD-012 contract
failure. The original oracle/API mismatch and single-object contention issue
were corrected; the remaining evidence is the intermittent provider behavior.

## Class B — inherited `/init` and real model sessions

Exact launcher command:

Run this command on a Unix-like host (Linux/macOS) or in WSL; the launcher
requires Unix-domain sockets and native Windows Python cannot provide the
credential-socket bridge.

```powershell
uv run --locked --project runtime python runtime/hermes-image/launch_routine_probe.py --image <resolved-local-image-digest> --credential-ref <opaque-reference> --model-profile-ref <authorized-synthetic-profile-reference> --setup-timeout-seconds 60 --probe-timeout-seconds 60
```

After authenticated readiness, the owned container invokes:

```text
/opt/hermes/.venv/bin/python /tmp/smoke_routine_sessions.py --mode service --timeout-seconds 60
```

The launcher uses a dedicated bridge network with no published ports. It does
not use Docker `--internal`, so a genuinely configured provider can be reached
over outbound HTTPS while the probe remains unexposed from the host.

The launcher keeps the Class B status **SETUP_BLOCKED** unless the inherited
`/init` container starts, authenticated readiness succeeds, and the service
probe reports its model-preflight and real-session assertion stages. The local
Unix proxy forwards only the validated bootstrap and model-profile references;
unknown, changed, oversized, or overlong responses are rejected or bounded,
and command evidence redacts opaque references and credential-shaped values.

Status: **SETUP_BLOCKED**. No secure inherited-`/init` launch, credential
socket/provider setup, authenticated readiness, or configured model
credentials were available. This is setup evidence, not a Hermes capability
failure. No overlapping real sessions, event attribution, canary isolation,
memory, or file assertion is claimed.

The focused deterministic test only proves that existing
`stable_session_identifiers` values are stable for retries, distinct across
the main/two routine conversation references, and different across profiles.
It does not prove simultaneous execution or shared durable state.
