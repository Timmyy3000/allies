# Workspace resource sizing

Deployment activation and image replacement read these shared control-plane
settings. Apply matching values to the API and background workers:

```text
WORKSPACE_CPU_KIND=shared
WORKSPACE_CPUS=2
WORKSPACE_MEMORY_MB=2048
WORKSPACE_VOLUME_SIZE_GB=10
ALLIES_RUNTIME_KEEP_WARM_SECONDS=1800
```

These are the defaults. Idle stopping still has its separate enable flag.
The CPU count is bounded to 1–16, memory to 1–131072 MB, volume size to
1–1000 GB, and CPU kind to shared or performance. The provider must support
the selected combination. Standalone lifecycle specs retain previous defaults
for existing callers; supply explicit values when using them directly.

Changing these settings does not resize an already-bound machine or volume.
New activation and replacement specs use the configured compute shape.
Existing correctly named/placed volumes must have at least the requested
capacity; larger volumes are retained, and undersized volumes fail without
being deleted or replaced.

Before changing a deployment's volume target, inventory assigned workspaces.
At a safe quiescent boundary, preserve each volume's identity and verify a
recovery snapshot, extend undersized volumes with the provider's supported
procedure, and check mounted filesystem capacity. Update or replace compute
while retaining the same volume, then verify current runtime readiness and
data continuity before resuming work. Never shrink a larger volume to match
the configured minimum.

Keep prior explicit sizing overrides during a compatibility deployment, then
switch to the intended sizing after resource preparation. Compute rollback
must still fit the workload; volume growth remains in place on rollback.
