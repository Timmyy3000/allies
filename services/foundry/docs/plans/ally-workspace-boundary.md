# Ally workspace boundary

Route: fast. HTML required: no. Base: `dev`; delivery: reviewed PR, no deployment.
Status: revised after boundary review; implementation has the proof gates below.

## Outcome and contract

Every Ally starts tools in its exact profile workspace and receives that absolute
path in internal context. Files created there can be published using either an
absolute path inside that workspace or a workspace-relative path. Relative
publication paths always use the workspace root, even after a terminal `cd`.
Errors tell the Ally what to correct without exposing private paths to product
events. The runtime, rather than model instructions, enforces publication scope.

All model-directed filesystem operations, including file tools, shell, generated
code, browser helpers, skill scripts, delegated agents and their descendants,
must be unable to write outside the active workspace and explicitly writable
profile state. Own skills, memory, cache and temporary state remain usable.
Shared skills and installed dependencies remain readable and immutable. Other
profiles and trusted runtime credentials/state remain inaccessible. The trusted
runtime retains its root identity and publication ownership.

Preserve the tenant's two-container topology, durable volume, concurrent
profiles, one active turn per profile, leases, transcript continuity, cancellation
and deletion fences. No file moves, workspace replacement, bulk permission
changes, unrelated UI work, or weakened approvals are included. Publication
activity is in scope across Foundry, Cloud and Interface: stable kind
`publish_files`, with “Publishing file”, “Published file” and “Couldn't publish
file” labels for running, successful and failed states. Structured failed
publication results must produce failed activity even when the handler returns
normally.

## Evidence and smallest viable approach

- `runtime/allies_runtime/profile_store.py` owns profile layout and managed
  configuration. Use its workspace identity rather than a new configurable root.
- Pinned Hermes `36cb5ae5530a75def7df3195e49b7a4aa2add482` resolves relative file
  paths through session cwd and task overrides (`tools/file_tools.py`), while
  local terminal execution only sets cwd (`tools/environments/local.py`). Neither
  enforces filesystem isolation. Delegate execution uses threads and seeds cwd.
- Hermes `gateway/platforms/api_server.py` scopes profiles through ContextVars.
  `_run_agent` uses a shared executor; `/v1/runs` has a separate executor path.
  There is no inspected per-profile process supervisor to reuse. A guard on one
  tool or one stream route cannot satisfy the requirement.
- `runtime/allies_runtime/files.py` already traverses publication sources with
  directory descriptors, no-follow checks, regular-file/link checks, size limits
  and immutable snapshot/retry handling. Reuse these protections after converting
  contained absolute input to the existing relative representation.
- `runtime/allies_runtime/publication_bridge.py` currently collapses local source
  failures into `publication_unavailable`; the publication plugin also discards
  non-ready responses. Both ends need the same small error contract.
- Nabu continuity and file-attachment specifications retain concurrent profiles
  on one tenant Machine, root trusted runtime versus UID-10000 Hermes, immutable
  publication and private chat links. The latest user instruction supersedes the
  specification's relative-only publication restriction; other safeguards stand.
- Coordinator kernel probes found no usable Landlock on the target deployment;
  the local kernel's older ABI also lacks the required complete write coverage.
  An unprivileged user/mount/PID namespace probe succeeded on the target. This
  establishes a candidate, not a proven sandbox or release readiness.

Proposed enforcement: one namespace-confined Hermes API process per active
profile, using a pinned, reviewed bubblewrap installation and the existing Hermes
HTTP protocol. Extend the existing trusted `APIServerAdapter` profile middleware
with a bounded child manager and scoped proxy; retain existing authentication
and the control boundary. The parent creates an AF_UNIX listener and passes only
its descriptor to that profile's child. Expose no child TCP listener or sibling
listener directory. Keep the parent inside the Hermes container and
the trusted runtime separate. This is the smallest currently identified approach
that covers arbitrary file and process tools without individual tool filters.

### Mount and credential contract

Keep immutable executables, libraries and `/opt/allies/skills` read-only. Mask
`/opt/data` with an empty read-only root and read-only `profiles` parent, then bind
only the selected profile at its canonical path. Its root remains writable own
state; overlay `.env`, `config.yaml`, `SOUL.md` and `.allies-profile.json` as
read-only file mounts, including refusal of unlink/rename replacement. Inventory
other runtime-owned control files and mask or protect them before readiness.
Missing required control files fail startup, rather than allowing child creation.

This preserves root `state.db` and `response_store.db`, journal/WAL/SHM creation
and SQLite writability preflight. Individual database binds beneath a read-only
parent are insufficient. Moving databases would break existing readers, including
API session lookup and deletion's session inventory. Known writable own-state
directories are `workspace`, `memories`, `sessions`, `skills`, `skins`, `logs`,
`plans`, `cron`, `home`, `cache` and `mnemosyne` (data under `mnemosyne/data`).
Prepare missing directories through trusted setup. Private `/tmp`, `/var/tmp`
and subprocess HOME/cache defaults stay within this namespace; durable paths
remain unchanged. Parent profile-directory replacement must be denied.

Expose only the root-owned publication bridge socket required by the existing
protocol, not its ledger/spool or API-listener directory. Use private PID/proc
views and close unrelated descriptors. Own credentials being readable by the
same profile is accepted. Other-profile, runtime and parent-control credentials
remain excluded. A credential broker or broader same-profile secrecy model is
not part of this fix.

## Implementation sequence

1. **Prove the boundary before selecting it for delivery.** Build a disposable
   fixture from the pinned image with all current patches. Inventory actual
   profile state writes and supervisor/API launch behavior. Prove bubblewrap
   works as the deployed Hermes UID without elevated capabilities. Give each
   child the mount policy above: read-only executable dependencies and shared
   catalog, a masked tenant-volume root, only its permitted profile mounts,
   private temporary storage and a private PID/proc view. Drop capabilities,
   prevent privilege gain and close unrelated descriptors. Do not bind the
   whole host root, tenant volume or shared `/tmp` writable. Validate all enabled
   execution paths and credential handling described under release gates.

2. **Align workspace context and defaults.** Extend the image overlay at the
   existing profile/session seam. Set the child's process cwd and initial
   session/task terminal cwd to the canonical workspace before agent execution;
   seed delegated tasks consistently. Expose one stable internal context message
   identifying the workspace and publication base. Keep session-local terminal
   cwd changes working inside the permitted tree and never change process-global
   cwd/environment in a concurrent shared server. Repair managed defaults
   idempotently for existing profiles without rewriting user files. Missing or
   unsafe workspace roots fail with a controlled error rather than falling back
   to a shared directory.

3. **Correct publication paths and errors independently.** In `files.py`, accept
   bounded relative input or contained POSIX absolute input, normalize to one
   workspace-relative identity and reject aliases that duplicate the same file.
   Keep existing refusal of traversal, hidden components, symlinks, hard links,
   directories, special files and unsafe sources. Both preparation and freeze
   use the same normalization. Preserve descriptor-based race resistance and
   frozen-version retry semantics. Update the plugin schema and parser to permit
   absolute paths; only the trusted runtime decides containment. Add safe,
   allowlisted results for `invalid_paths`, `file_not_found`, `file_unreadable`
   and `file_too_large`; retain `publication_unavailable` for infrastructure
   failures. Correctable messages say to create/copy the file into the current
   workspace and retry; they do not echo rejected paths or exception strings.
   Preserve count/byte limits and ready `chat_reference` output unchanged.

4. **Integrate bounded profile processes after step 1 passes.** Extend parent
   `APIServerAdapter` middleware to proxy authenticated scoped execution/session
   requests over its private child AF_UNIX connection. Parent retains public
   authentication, detailed health and authoritative quiescence/control routes;
   child serves forwarded profile operations and never owns the external fence.
   Maintain an exhaustive method/path ownership table from the actual adapter
   route table: parent control, child profile operation, or explicitly denied.
   Enumerate session CRUD/history/bootstrap, chat/stream, completions/responses,
   `/v1/runs`, approvals, cancellation, routines and quiescence. Startup fails
   closed if an execution-capable route has no explicit classification; no
   catch-all forwarding or fallback parent execution. Test the real registered
   routes against ownership, including both prefixed and unprefixed forms.
   Deny parent model execution on every route, including `/v1/runs`, and deny
   child unscoped access except the internally forwarded, already-scoped request
   after prefix removal. Child multiplexing stays disabled. Start on demand within
   existing runtime capacity; serialize duplicate launches; bound startup and
   shutdown by existing request/lease budgets. Forward streaming and disconnects
   without buffering whole turns. Preserve session creation/read/bootstrap,
   approvals, cancel and routines. Sandbox startup proof contributes to existing
   detailed readiness and fails closed before admission. Child exit produces
   an honest failure/unknown-safe outcome, never automatic turn replay. Deletion
   closes admission, terminates namespace PID 1 and reaps every descendant. Only
   then may the parent issue the existing instance/generation-bound quiescence
   proof before state removal. Child identity is internal and cannot replace
   the established fence. Do not spawn extra tenant Machines.

   Add `publish_files` to runtime normalization, backend validators and
   `docs/contracts/activity-presentation-v1.json`; update the corresponding
   Cloud validator/projection contract and Interface web/mobile label mappings
   after inspecting their repository instructions. Extend the existing activity
   overlay to map direct and wrapped publication calls consistently and classify
   their structured `state: failed` results as failure. Keep stable call identity
   across start/completion and retries; do not export arguments, paths, tokens or
   raw failure payloads. This adds a known kind to the existing activity contract,
   not a second event stream. Coordinate consumer-first deployment compatibility;
   deployment itself remains outside this episode.

5. **Validate, document and hand off.** Run focused runtime and image tests,
   then the existing validation and complete image smoke targets below. Update
   `docs/operations/hermes-capabilities.md` with the boundary and unsupported-host
   behavior, and reconcile accepted Nabu contracts through the coordinator.
   Obtain separate correctness/security and simplicity reviews. Deliver
   independent preparatory publication and activity slices as coherent PRs,
   ordered consumer-first across Interface/Cloud contract acceptance and Foundry
   production of `publish_files`; retain existing unknown-kind compatibility.
   Publication path/error correction can proceed independently with its tests.
   Deliver namespace confinement and required workspace defaults in a separate
   dependent PR. All slices remain part of this task's completion scope;
   preparatory PRs do not complete confinement. No deployment or
   production mutation is part of this episode.

## Required validation and release gates

| Requirement | Passing evidence |
| --- | --- |
| Consistent defaults | Real patched Hermes API turn for two profiles with different roots and an unrelated parent cwd; first file write, first terminal `pwd`, subsequent `cd`, delegate, resumed session and routine all use the expected profile. Internal workspace paths do not leak into product events. |
| Publication | Real temporary files cover contained absolute/relative success, normalized duplicate rejection, missing file, denied read, size/count/total limits, outside/prefix-sibling paths, traversal, hidden files, symlinks and source replacement. Retry preserves the same frozen bytes and never produces a ready link on failure. |
| Filesystem confinement | Execute actual file, patch, shell, generated-code, browser/helper and child-agent paths in the built sandbox. Verify own writes and shared reads succeed; writes to shared resources, reads/writes of another profile and access to runtime state fail. Exercise subprocess descendants, background work, rename/link/truncate and descriptor/proc access using generic fixtures. Assertions inspect outcomes, not source text. |
| Credentials and transport | Own credentials are allowed; other-profile, runtime and parent-control keys never enter child mounts/environment/descriptors. Own control-file writes and replacement fail. A sibling cannot reach a child listener; child requests cannot execute tools in the parent. |
| Publication activity | Direct/wrapped calls use the same stable `publish_files` identity through Foundry, Cloud and web/mobile. Running/ready/failed render the required labels. A structured failure yields failed activity, not success. Retries follow existing identities and no path, token or raw payload enters activity events. |
| Concurrency/lifecycle | Two profiles overlap without exchanged cwd, state, credentials, events or reused execution resources. Repeated launch, startup failure, process crash, disconnect, approval wait, cancellation, profile quiescence, routine execution, deletion and volume restart preserve the existing contracts. No surviving writable child after successful quiescence. |
| Capability failure | Missing sandbox executable, unsupported namespace setup or unsafe mounts make existing detailed readiness/admission fail before model/tool execution. Test in the actual deployment-equivalent environment; an ordinary host pytest pass is insufficient. |
| Route ownership | Every registered method/path has explicit parent/child/denied ownership; an unclassified execution route prevents startup. Prefix variants, `/v1/runs` and direct child access cannot execute outside the intended sandbox. |

Exact existing checks, with `DJANGO_DEBUG=true` where required:

```sh
make check
make lint
make validate
make runtime-test
make hermes-image-build
docker build --tag allies/runtime:workspace-boundary --file runtime/Dockerfile runtime
sh runtime/hermes-image/smoke_release.sh allies/hermes-mnemosyne:dev allies/runtime:workspace-boundary
```

Add the focused workspace/confinement smoke to `smoke_release.sh` and run the
publication tool/socket checks explicitly if they are not covered by that suite.
Focused runtime tests belong beside `runtime/tests/test_files.py`,
`test_publication_bridge_failures.py` and `test_publication_spool_failures.py`. Hermes upstream
checks, when useful during overlay development, use `scripts/run_tests.sh` in a
disposable pinned checkout. CI definitions inspected: `.github/workflows/ci.yml`
and `hermes-image.yml`; preserve locked tooling, identity, coverage and security
gates. These are planned checks, not reported passing results.

## Accepted review dispositions

All boundary findings `ADV001`–`ADV006` and simplicity findings `SIM001`–`SIM002`
are accepted. The six boundary dispositions are implemented together in this
plan: private inherited-FD child transport; parent-authoritative quiescence and
descendant reaping; accepted own-credential visibility with immutable managed
controls and a SQLite-compatible mount layout; reuse of the authenticated parent
adapter with explicit execution ownership; fail-closed detailed readiness; and
complete publication activity/failure handling without path leakage. These are
implementation requirements, not claims that proof has passed.

`SIM001`: the adapter owns an exhaustive route classification and refuses startup
for unknown execution routes. `SIM002`: publication/activity preparation ships
in independent coherent PRs with consumer-first dependencies; namespace
confinement is a separate dependent PR. This sequencing does not defer any
accepted user requirement or authorize deployment.

## Open decisions, risks and rollback

- Own-profile credential visibility is accepted; readonly managed controls and
  exclusion of other profiles/runtime remain mandatory. Root SQLite and atomic
  managed-control replacement need actual mount tests. A trusted configuration
  update requires draining/restarting the child so file mounts cannot keep stale
  credentials/configuration pinned after an atomic replacement.
- The child manager adds lifecycle machinery inside the existing parent adapter.
  Verify route coverage, private descriptor transport, bounded cleanup and
  parent-owned readiness/quiescence against the existing protocol. A new protocol or
  broad Hermes fork is not authorized by this plan.
- Private mounts may break existing cache, memory database, skill installation,
  browser or subprocess-home behavior. Use the write inventory from step 1 to
  grant the narrow paths required; do not resolve failures by mounting the
  tenant root writable. Own managed configuration and control files must not be
  casually made model-writable.
- Production namespace availability, sandbox package provenance/pinning and
  resource overhead need concrete proof. If proof fails, retain the preparatory
  fixes and report confinement blocked; no path-guard-only release substitute.
- No destructive migration is expected. Existing profiles keep their paths and
  durable state. Roll back the image/overlay together only after draining and
  reaping children. Once confinement is promised, rollback must stop affected
  execution rather than silently restore unrestricted tools. Publication
  compatibility can roll back independently without deleting frozen artifacts.
