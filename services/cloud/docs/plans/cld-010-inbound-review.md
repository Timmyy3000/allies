# Inbound implementation review

## Scope

- Cloud inbound: 529d3cc.
- Foundry inbound: 2c2723e and image correction b2d5fc6.
- Inspection helpers: 41198fc, 9a15eb8, 20ee33b, and cb83426.
- Separate sol_high workers performed simplicity and correctness reviews.
- The coordinated inbound findings have corrections and regression tests. The final publication reviews are separate.

## Inspection findings

| Finding | Correction | Evidence |
| --- | --- | --- |
| A seekable source was read to its end before the size check. | Stop after the declared byte limit. | An oversized source stops within one chunk. |
| Office validation trusted ZIP metadata and macro filenames. | Count central records before allocation. Read all entries with bounded expansion and CRC checks. Parse XML without DTDs, entities, or a document tree. Reject macro metadata. | Corrupt headers, CRC errors, false entry counts, macro metadata, and entities fail. |
| An arbitrary scanner prefix could return a clean verdict. | Require the exact `stream: OK` response. | Invalid prefixes and extra fields fail closed. |
| An image-size warning escaped the preview boundary. | Return the safe large-image fallback. | A 100-megapixel header returns no preview. |
| Filename validation depended on the host platform. | Reject both separators, drive prefixes, and control characters. | Cross-platform path cases fail. |

The final focused helper run passed 26 tests. Ruff passed. These checks do not
prove scanner deployment or process isolation.

## Inbound simplicity findings

Foundry commit 0105a00 removes an unused transport response shape, an unused
awaitable fetch path, and a duplicate redirect handler. Parent verification
passed 129 affected runtime tests. The worker also passed two backend tests.

The reviewer recommended one shared Cloud service-token helper. The worker
deferred this change because it would also change unrelated application routes.
New file routes use the existing file-domain helper with the same Bearer token
boundary. This is a simplicity recommendation, not an authorization defect.

## Pinned image check

The incoming patch had invalid hunk counts. Commit b2d5fc6 corrects the patch
and adds a build-time context smoke check. The complete overlay chain applies
to Hermes source 36cb5ae. Python compilation and extracted source-function
checks pass. The full container build has not run locally.

## Coordinated correctness findings

The fresh reviewer reported these cases. The committed corrections have local
regression evidence. The final reviewers must also check the integrated flow.

| ID | Correction | Regression evidence |
| --- | --- | --- |
| CR-001 | Retry preserves cleanup fences, locks the storage account, and reserves bytes again only after confirmed cleanup. | Cloud cleanup retry test checks one reservation. |
| CR-002 | An old retry request replays the committed next generation after receiving or validation starts. | Cloud cleanup test replays a receiving generation. |
| CR-003 | Names use the agreed 255-character bound. Disk names use generated identifiers. | Foundry staging tests include long Unicode names. |
| CR-004 | Preparation checks owner, workspace, Ally, direction, and protection. | Cloud tests reject foreign owners and corrupt ancestry. |
| CR-005 | Cancel and remove fence validation. Promotion checks original authority after object I/O. | Cloud PostgreSQL tests race cancellation or removal against promotion. |
| CR-006 | Lease loss stops staging before writes or receipt commit. | Foundry worker test proves no receipt and no Hermes call after lease loss. |
| CR-007 | Permanent Cloud file errors are terminal. Transient open retries are bounded. | Foundry proxy and transport tests cover these responses. |

The prior inspection helper corrections passed the fresh recheck. The later
isolated-process adapter needs its own review. Its local suite passed 33 tests;
one real POSIX process test is skipped on Windows and is available to Linux CI.

## Security preflight

Gitleaks 8.30.1 found no leaks in the committed Cloud and Foundry changes at
the pre-publication checkpoint. The final publication commits need another scan.
The public Foundry document and image diff contained no private Nabu or local
workspace references in the targeted check.
