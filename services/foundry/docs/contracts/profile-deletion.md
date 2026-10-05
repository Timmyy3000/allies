# Profile deletion v1

Cloud owns the user confirmation and product operation. It calls
`POST /api/v1/internal/profile-deletion` with the existing Cloud service bearer
credential and the versioned request in `foundry-profile-deletion-v1.json`.
The external workspace ID resolves to the existing local workspace; the
binding ID derives the same canonical profile UUID used by provisioning.
Existing profile identity must match the ally and workspace before any mutation.

Repeated requests return the same attempt or terminal marker receipt. A pending
attempt has an immutable UUID, lifecycle epoch, digest and expiry (24 hours).
An expired attempt remains unresolved. An operator using the service credential
may POST the same request plus `expected_attempt_id` to
`/api/v1/internal/profile-deletion/resume`. That creates one successor; duplicate
resume returns that successor and stale expected attempts return 409. There is
no implicit renewal through status polling. Callers use a bounded transport
timeout and retry the same operation after an ambiguous response.

Deletion immediately fences profile provisioning, new executions and routine
commands. Existing leases enter STOPPING. Reconciliation includes
`cleanup_requires_quiescence` and `cleanup_attempt_id` alongside the existing
cleanup operation, epoch, digest and expiry. An absent database profile still
requires runtime absence proof: it may have left files on the tenant volume.

A deletion cleanup receipt includes `attempt_id`, `machine_generation`,
`runtime_start_epoch`, `runtime_boot_id`, `hermes_instance_id` and `quiescence`.
The runtime proves closure against the current Hermes process before deleting
profile storage. The backend accepts success only for the current, unexpired
attempt and ready worker boot, with zero unresolved leases and zero active runs,
profile I/O, open stores and owned children. Missing capability, stale evidence
or incomplete resource closure cannot report success. Legacy ordinary cleanup
remains compatible and does not substitute for deletion proof.

The pinned Hermes overlay advertises `profile_quiescence_v1` and a fresh
`hermes_instance_id` at `/v1/capabilities`. Only its listener-root process
credential can call `POST /v1/profiles/{profile_key}/quiesce`; profile-prefixed
mirrors and profile credentials are rejected. The runtime writes its durable
pending fence first. The root-owned marker uses a numeric Unix expiry, while
the backend wire contract carries an ISO timestamp.

The overlay tracks actual executor and SDK threads independently of cancelled
HTTP wrappers, drains profile requests, checks provider/client closure, erases
owned run queues/statuses and response rows, and closes the cached SessionDB.
The memory wrapper closes the pinned library's beam, audit and owned cached
connections explicitly; failed shutdown prevents reinitialization from replacing
the unresolved owner. Closing one provider preserves the process-wide model
backend while another remains active. After draining unreachable SQLite cycles,
the Linux endpoint verifies that no process file descriptor still points inside
the target profile before issuing its proof.
It verifies task ownership before closing local processes, terminal environments
and local browser sessions. Other allies' task IDs, stores and processes remain
untouched. Unknown orphan browser ownership, external Camofox/browser backends,
or non-local terminal environments fail closed and require repair; they are not
treated as erased merely because an in-memory registry is empty. A runtime
upgrade does not retroactively prove ownership of an orphaned external resource.

`runtime/hermes-image/smoke_profile_quiescence.py` runs inside the actual pinned
image at build time with synthetic data. It covers live-thread cancellation,
checked SQLite/provider closure, owned process termination, sibling preservation,
run/response cache erasure, admission fences and a fresh-process terminal replay.

After verified runtime deletion, the coordinator deletes protected routine and
publication children before cascading the profile's conversations, executions,
attempts, leases, approvals, event deliveries and provisioning hints. It removes
routine command receipts scoped by ally or routine execution. It preserves other
profiles and shared workspace, machine, volume, credentials and release state.

The only terminal record is `DeletedProfile(workspace_id, profile_id)`, with no
content or credentials. Provisioning checks this marker before creation. The
terminal receipt ID is derived from those opaque identifiers. Cloud separately
owns erasing its object storage and product data before reporting user-visible
completion. Existing infrastructure backup retention is outside this active-store
protocol and is not silently changed by deleting an ally.

Roll out the runtime capability and backend migration before enabling Cloud's
deletion API, then the Interface flow. An older runtime cannot provide the
required proof, so deletion remains pending or requires repair. Do not roll back
admission fences while accepted deletion operations or terminal markers exist.
