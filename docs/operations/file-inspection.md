# File inspection operation

## Scope

`files.inspection.inspect_file` validates a private object and scans it before
the intake service can promote it. The helper accepts a binary stream with the
declared size. It reads in 64 KiB blocks. A non-seekable stream
uses a bounded temporary file. The helper does not log file content, paths, or
scanner responses.

The caller must provide a `ClamAvClient` with an explicit `ScannerConfig`. It
uses a private ClamAV daemon transport. A clean result requires a valid type
and the exact `stream: OK` response from that transport. The helper fails closed for a scanner
timeout, unavailable scanner, invalid response, stale definitions, or malware.
Definitions must be 24 hours old or newer. The scan deadline is 60 seconds.

## Type controls

The extension mapping is the existing inbound manifest mapping. The helper
checks image and PDF magic, bounded UTF-8 for text and code, and Office
containers. OOXML files must contain the expected main part. The helper rejects
encrypted Office containers, VBA macro parts, malformed containers, more than
1,000 entries, and more than 100 MB of expanded Office content. Legacy Office
`.doc`, `.xls`, and `.ppt` files fail closed as `office_legacy_unsupported`.
They need an approved isolated Compound File Binary parser before release.

The OOXML preflight counts central-directory records before the ZIP reader
allocates entries. The reader checks every local header and CRC with bounded
decompression. The XML parser rejects DTDs, entities, external references, and
macro metadata. XML parsing uses no document tree and limits depth to 128.
Run these helpers in the isolated inspection worker before production enablement.

`files.isolated_inspection.inspect_isolated` starts a separate POSIX parser
process. It removes the application environment, disables core dumps, and
limits memory to 512 MiB, CPU time to 65 seconds, output to 4 KiB, and wall
time to 90 seconds. The parent stages at most the declared file size before
starting it. Systems without these process limits fail closed. The child
imports the file type policy without Django or database settings. This process
boundary does not replace the private scanner deployment or filesystem review.

Private previews use the same process boundary. The preview operation permits
at most 16 MiB of encoded output. The parent accepts only PNG images, escaped
text, or a safe unavailable result. Native image decoding does not run in the
web process. Unsupported previews still permit a clean download.

## Preview controls

`files.previews.build_preview` has no storage or HTTP behavior. It re-encodes
JPEG, PNG, GIF first frames, and WebP previews as PNG after a 40-megapixel
check. It returns escaped text previews up to 1 MB. It returns no preview for
Office files. PDF preview needs an isolated raster worker. HEIC and HEIF preview
needs a reviewed decoder. Both return safe unsupported results until those
components exist.

## Integration

The task worker reads the private object from the private storage port and
calls `inspect_isolated`. It promotes only an accepted result. It maps
the verified size, SHA-256, media type, and accepted result to the existing
`files.services.intake.InspectionResult`. A fake test transport is only unit
test evidence. It is not scanner-image or decoder proof. Keep production file
admission disabled until scanner deployment, preview isolation or decoder
decisions, serving limits, capacity approval, and deletion integration are
complete.

The task claims a 240-second inspection lease with a unique token. Promotion
must check that token, its deadline, the generation, and the write fence after
storage I/O. A stale worker cannot promote or reject a replacement generation.

Durable uploads notify a file-specific inspection task only after their database
transaction commits. Retryable failures persist their 5- or 30-second due time
before publishing the next notification. Notifications use a short, non-retrying
broker connection and may be lost without losing work: the bounded 30-second
due-file sweep remains the recovery path for broker failure, worker restarts,
and expired leases. Duplicate, early, leased, terminal, and missing-file tasks
must therefore remain safe no-ops.

The official ClamAV image starts FreshClam and clamd independently. If an update
finishes before the daemon socket exists, notification can be missed. Railway's
staging and production scanner services set `CLAMD_CONF_SelfCheck=10` so clamd
detects that database replacement within ten seconds; `FRESHCLAM_CHECKS=12` and
the persistent signature volumes remain enabled. After every scanner deployment,
verify the configured self-check interval, a successful database status check,
the daemon-reported definition timestamp, and a benign scan before accepting
files. Container deployment success alone is not scanner-readiness evidence.
