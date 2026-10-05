# Reading a readiness timeline

The target is **less than five seconds from a wake/create request to a usable
Ally**, including an existing sleeping workspace. Instrumentation does not mean
that target has been achieved. Keep new-account pool hits, empty-pool provisioning,
awake creation and sleeping-workspace wake samples separate.

## Capture

Deploy both the control-plane changes and the matching runtime image. Existing
Machines running an older image cannot emit the new runtime stages. Collect
Cloud and Foundry service logs and the runtime container's logs for the same
test window; runtime stdout lives with the Machine, not automatically in the
control-plane service logs.

Keep `ALLIES_WIDE_EVENTS_ENABLED=true`. The new critical readiness stages are
retained independently of generic success sampling. For a diagnostic test, use
`ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE=1` to also retain existing provider and
provisioning detail. Existing bounded sinks can still drop events:
missing evidence must not be interpreted as a zero-duration step.

## Cloud events

Events use `runtime.operation.started`, `.succeeded` and `.failed` with the
following `operation` names. A succeeded span means that call returned; inspect
its `outcome` before concluding the Ally is ready.

| Operation | Meaning |
| --- | --- |
| `wake.forward` / `creation_wake.forward` | Cloud-to-Foundry intent round trip, with returned waking/ready/rate-limited status |
| `provisioning.reconcile` | Complete reconciliation attempt, including local work and external calls; terminal outcome may be deferred or repair-required |
| `provisioning.profile_roundtrip` | Profile registration/readiness receipt round trip |
| `provisioning.activation_roundtrip` | Workspace activation round trip |
| `readiness.hint_received` | Accepted hint recorded after transaction commit; an instant, not a duration |
| `readiness.hint_dispatch` | Failed task publication with `broker_unavailable`; the durable due scan remains the fallback |
| `readiness.hint_to_dispatch_wall` | Wall time since the latest stored hint when this reconciliation starts |
| `provisioning.ready_committed_wall` | Wall time since the durable provisioning operation was created, emitted after successful readiness/handoff commit |

Provisioning `correlation_id` is the existing Cloud operation UUID; intent
forwarding uses the existing idempotency UUID. Hint receipt includes the hint
UUID in `request_id` to join to the Foundry publisher. Resource identities are
hashed by the event builder; hashes from different service keys are not
interchangeable. Do not distribute application authentication secrets to make
hashes match.

Manual recovery clears the previous hint marker, so an old hint does not
inflate the next hint-to-dispatch sample.

## Foundry control-plane stages

| Operation | Measured work |
| --- | --- |
| `runtime.intent` | Intent acceptance/coalescing, with its terminal event after commit |
| `runtime.wake.queue_wait_wall` | Current attempt's scheduled time to maintenance processing |
| `runtime.wake` | One maintenance wake attempt; success can mean only `awaiting_readiness` |
| `runtime.wake.machine_state_observation` | Existing initial provider inspection and binding validation |
| `runtime.wake.machine_start_request` | Provider start API round trip; acknowledgment is not runtime readiness |
| `runtime.wake.machine_started_observation` | Existing inspection after an uncertain start response |
| `runtime.wake.request_to_attempt_end_wall` | Current attempt's scheduled time to the end of provider orchestration |
| `runtime.wake.retry_scheduled` | Committed retry bridge linking the old and new operation UUIDs; an instant, not a duration |
| `runtime.readiness_receipt` | Validated runtime readiness, with success only after commit |
| `runtime.readiness.scheduled_to_commit_wall` | Current attempt's scheduled time to committed runtime readiness |
| `runtime.profile_materialization_receipt` | Validated materialization receipt through commit |
| `readiness.hint_send` | Foundry-to-Cloud hint round trip; only HTTP 202 is successful |

Existing `workspace.provision.*` and `workspace.replace.*` phases cover app,
volume and machine creation, start, health, activation gate and binding where
applicable. Their start helper emits `workspace.machine_start_request` and
`workspace.machine_started_observation` separately. These phases now include the provisioning operation
correlation; their parent spans overlap with the child stages.

## Runtime stages

| Operation | Measured work |
| --- | --- |
| `startup.setup` | Configuration, credential resolution and initial clients |
| `startup.hermes_readiness` | Aggregate authenticated Hermes health wait, including polling; timeout is a failed terminal |
| `startup.composition` | Profile-store and worker composition |
| `worker.initialization` | Initial reconciliation/readiness loop, including retries |
| `profile_reconciliation` | One full profile reconciliation pass |
| `profile.reconciliation_fetch` | Desired-profile snapshot request |
| `profile.local_materialization` | Local profile-store work |
| `profile.materialization_receipt` | Materialization receipt round trip |
| `profile_materialization` | Parent span covering local materialization and its receipt |
| `profile.reconciliation_retry_wait` | Actual existing retry sleep, with retry count |
| `readiness.hermes_health` | Authenticated Hermes check before publishing readiness |
| `readiness.publication` | Runtime-to-Foundry readiness receipt round trip |

The runtime's `correlation_id` is its existing boot UUID, now shared from the
first startup span through readiness publication. Materialization child spans
also carry the operation UUID in `request_id`. Generation and start epoch are
included after the reconciliation snapshot supplies them. Missing or malformed
optional logging metadata does not reject an otherwise valid snapshot.

These critical runtime stages are retained regardless of generic success
sampling. Profile execution/turn events keep their existing sampling behavior.

## Join one test across services

Search structured fields, retaining each event's UTC time, operation, outcome,
duration and retry count. Follow these explicit bridges rather than comparing
resource hashes generated with different service keys:

| Bridge event | `request_id` | `correlation_id` |
| --- | --- | --- |
| Foundry `runtime.intent` completion | Intent idempotency UUID (Cloud forwarding correlation) | Foundry wake operation UUID |
| Foundry `runtime.wake.retry_scheduled` | Previous wake operation UUID | Next wake operation UUID |
| Foundry `runtime.readiness_receipt` completion | Runtime boot UUID | Foundry wake operation UUID when a wake is active |
| Runtime `profile.materialization_receipt` | Materialization operation UUID | Runtime boot UUID |
| Foundry `runtime.profile_materialization_receipt` completion | Materialization receipt UUID | Materialization operation UUID |
| Foundry `readiness.hint_send` | Hint UUID | Materialization receipt UUID |
| Cloud `readiness.hint_received` | Hint UUID | Cloud provisioning operation UUID |

For an already-ready heartbeat there may be no active wake operation. For
normal provisioning or an empty-pool fallback, also inspect existing
`workspace.provision.*`, activation and provider-operation timings. Their
parent/child spans overlap; pool assignment avoids those provisioning stages
in the signup request rather than making their historical work disappear.

## Interpret the measurements

`duration_ms` on local spans comes from a monotonic clock. Wall-clock intervals
are explicitly named `_wall`; they include queue/retry gaps and can be affected
by clock adjustments. UTC `occurred_at` supports timeline alignment across
hosts only to the accuracy of their clock synchronization.

An execution retry gets a new wake operation UUID and a new scheduled time.
The current attempt's `_wall` metrics therefore do **not** measure the whole
original user wait. Follow every `runtime.wake.retry_scheduled` bridge back to
the original intent, and measure from that intent to final readiness. Preserve
the retry/backoff gaps; a fast last attempt does not make the overall wake fast.

Do not sum overlapping parent and child spans. A machine-start API response is
not proof that Hermes or the Ally is ready. Keep provider state observation,
authenticated runtime readiness, profile materialization and Cloud readiness
as distinct milestones. A missing completion may mean process termination or
lost telemetry; preserve it as an incomplete attempt.

The normal wake path does not add a provider polling loop for diagnostics.
Where it has only the start API response, the interval until `startup.setup`
begins remains a platform/container/process-start gap. Use provider lifecycle
timestamps to split that gap further. The first Python event cannot measure
interpreter imports that ran before the entrypoint, and the authenticated
Hermes health wait does not expose every internal Hermes initialization step.

Backend readiness also excludes browser delivery and rendering. Measure the
actual “Waking up” interval in the client when evaluating the user-visible
five-second target. Report sample count, median, p95 when the sample supports
it, and maximum; retain slow and failed runs. First-token and completed-reply
latency are separate from readiness.

No new timing table or migration is introduced. Existing durable operation,
lease and readiness timestamps remain authoritative for recovery; these logs
explain the stages between them.
