# CLD-010 Nabu evidence

Read on 2026-09-08. These are source snapshots, not replacement canonical records.

## Source: projects/allies/engineering/specs/cld-010-user-message-file-attachments.md
Revision: e8a30bf1eb812c614f4a00c815e6486749bcdec4f9ea26ce9b77731f5f18fa46

---
title: Files sent to and returned by Allies
summary: Beta specification for sending files to an Ally and receiving durable, private file links in return.
status: Ready for Plan
ticket: projects/allies/delivery/tickets/cloud/CLD-010.md
owner: Timi
affected_repositories_or_systems: [allies-cloud, allies-interface, allies-foundry, Design]
tags: [allies, specification, files, beta]
authors: [Allies]
source: product-owner grill session on 2026-09-08
updated: 2026-09-08
---

# Files sent to and returned by Allies

## Specification metadata

- **Status:** Ready for Plan
- **Ticket:** [[projects/allies/delivery/tickets/cloud/CLD-010|CLD-010]]; [[projects/allies/delivery/tickets/design/DSN-008|DSN-008]], [[projects/allies/delivery/tickets/foundry/FND-011|FND-011]], and [[projects/allies/delivery/tickets/interface/INT-106|INT-106]].
- **Owner:** Timi
- **Affected repositories or systems:** Cloud, Foundry, Interface web and mobile, Design.
- **Related decisions and sources:** [[projects/allies/engineering/specs/cld-004-conversation-and-message-lifecycle|Message lifecycle]], [[projects/allies/product/allies-product-design-spec|Product design specification]], [[projects/allies/delivery/tickets/design/DSN-002|Conversation design]].
- **Last updated:** 2026-09-08
- **Template source:** [[projects/allies/engineering/specs/spec-template|Allies engineering specification template]]
- **Confirmation:** Approved by Timi on 2026-09-08 for planning and ticket breakdown.

## Problem

Users need to give their Allies documents, photos, and other files to work with.
Allies also need to return files they create or already have. Both directions
need clear progress, recovery, private access, and links that keep working when
the user returns later.

## Intended outcome

On web and mobile, a user can send files with or without text, receive files
through links in an Ally's reply, and open or download those files later.
The Ally retains access to its working files and can reuse them in later work.

## Deliverables

| Deliverable | Type | Owning repository or system | Completion evidence |
| --- | --- | --- | --- |
| Photos, Camera, and Files selection; outgoing files, progress, failure, retry, removal, cancellation, and queued-message states on web and mobile | Screens and interaction notes | Design | Product review covers the complete sending journey and the existing Figma retry treatment |
| File-link modal showing supported previews, file information, Download, loading, and failure states | Screens and interaction notes | Design | Both directions and download-only formats are covered |
| File intake, message association, private preview/download access, stable shared versions, and deletion behavior | APIs, data model, policies | Cloud / CLD-010 | Limits, ownership, delivery ordering, retries, and retrieval are demonstrated |
| Making incoming files available to the intended Ally and publishing existing or newly created files for return | Integration | Foundry | The Ally uses an incoming file, returns a file, and retries failed publication without recreating it |
| Selection, upload, recovery, per-Ally queue behavior, file links, and modal on web and mobile | Application behavior | Interface | Both clients demonstrate the agreed journeys |
| Shared contract and complete sending/returning proof | Contract and tests | Cloud, Foundry, Interface | A sanitized end-to-end demonstration covers success, failure, authorization, and later retrieval |

These are the four ticket boundaries: Design, Cloud, Foundry, and Interface.
Exact visual treatment belongs to Design; implementation approach belongs to
the engineers.

## User journey

1. Beside the textbox, the user chooses Photos, Camera, or Files. Selecting a
   file does not upload it. The user can remove it before sending.
2. The user adds optional text and presses Send. A message containing only
   files is valid; a message with neither text nor files is not.
3. The message immediately appears in the conversation as processing/uploading,
   with progress on each file. It is not yet delivered to the Ally.
4. When every file is ready, the text and files reach the Ally together.
   Further messages to that Ally may queue but cannot overtake this message.
5. If an upload fails, the message shows Failed. The user retries only the
   failed file or removes it, then explicitly retries sending. Successful
   uploads are retained.
6. Before delivery, the user can cancel the outgoing message. Uploads stop and
   text and selected files return to the textbox for editing or discarding.
   A successfully cancelled message must not later reach the Ally.
7. Switching Allies does not interrupt uploads or other ongoing activity.
   Returning shows current progress or the result.
8. If closing or refreshing the app interrupts an upload, the unsent message
   remains available with Retry. Ask for the file again only when the device
   can no longer access it.
9. The Ally can use received files in this and later turns. If it cannot read a
   supported file, it explains the limitation and asks for a usable format;
   successful delivery must not imply successful understanding.
10. The Ally returns a newly created or existing file through a link in its
    response. Each send refers to a fixed version; later changes produce a new
    link and do not alter earlier versions.
11. Clicking a sent or received file opens a modal. Images, PDFs, text,
    Markdown, and code show a preview with Download. Other formats show file
    information and Download without a content preview.
12. If returning a file fails, show the failure with Retry. Retry sends the
    existing file again without recreating it. Do not expose a broken link.
13. The signed-in owner can revisit old messages and retrieve their file
    versions for as long as the Ally exists.

## In scope

- Sending and returning files on web and mobile.
- Photos, Camera, and Files as distinct selection options.
- Images, PDFs, Word documents, spreadsheets including CSV, presentations,
  plain text, Markdown, and common code files including JavaScript and HTML.
- An extensible allowlist so additional formats can be added later.
- Private previews/downloads, immutable shared versions, retry and cancellation.
- Ongoing work independent of which Ally the user is currently viewing.

## Out of scope

- Public or third-party sharing through copied links.
- A general file manager, file editor, or visible version-history interface.
- Whole-drive, folder, or connected-library imports.
- Audio, video, archives, and executable binaries in the initial allowlist.
- Office-document previews in the first release.
- Choosing storage providers or prescribing implementation modules in this spec.

## Product constraints

- Initial defaults, chosen under the owner's delegated discretion: 25 MB per
  file, 10 files per message, and 50 MB total per message, in both directions.
- Use plain terms: textbox, file attachments, Photos, Camera, Files, Retry,
  Remove, Download.
- Processing/uploading is distinct from a later queued message and from
  confirmed delivery.
- A failed first message holds later messages for that Ally until retry
  succeeds or the first message is cancelled. Other Allies continue normally.
- Removing the last file from a file-only message must not deliver an empty
  message.
- Sharing does not remove the Ally's working copy.
- File links appear naturally within the Ally's response; standalone cards are
  not a required returned-file design.
- The modal exposes file name, type, and size along with the applicable preview
  and Download action.
- Camera permission or availability problems must be understandable and leave
  the other selection options usable.
- Existing Figma retry designs are a required input to the Design ticket, not
  an assertion that those designs were inspected during this grill.

## Technical constraints

- Cloud owns customer-facing file identity, message association, authorization,
  shared-version availability, and delivery state.
- Interface uses Cloud's product contract. Storage credentials and runtime
  addresses must not be exposed to users.
- Foundry owns availability to the intended Ally and access to its working
  files through the existing workspace continuity contract.
- File access must remain scoped to the correct owner and Ally; possession of
  a link alone is not authority.
- Retries must not duplicate messages or accidentally target newer work.
- Cancellation and completion races must resolve to one truthful outcome.
- Working-file changes and machine replacement must not change or erase
  previously shared versions.
- Exact schemas, storage choices, transfer mechanics, and inspection tooling
  belong to engineering planning.

## Cross-team API and data contract

| Capability | Required behavior and information | Owner |
| --- | --- | --- |
| File intake | Original name, recognized type, size, stable reference, owner/Ally association, readiness or failure; enforce the same limits shown by the clients | Cloud |
| Message delivery | Optional text plus all accepted file references; one idempotent message; no partial delivery or overtaking | Cloud; Interface consumes |
| Incoming file access | Intended Ally receives access to the accepted files, with bounded authorization and explicit access failures | Cloud and Foundry |
| Returned file publication | Publish a specific existing file version; confirm availability before exposing its link; retry the same version without regenerating it | Foundry and Cloud |
| File opening | Stable product link resolves to authorized metadata, supported preview content, and download; unsupported preview does not prevent download | Cloud; Interface renders |
| Recovery | Distinguish upload failure, message-send failure, returned-file failure, and retrieval failure; retain successful work for retry | All three repositories |
| Deletion | Ally deletion revokes access and removes its uploaded files and shared versions under the deletion contract | Cloud and Foundry |

Text-only messages and older conversation history must continue to work.
Publishing a returned file is distinct from the Ally deciding to create or
edit a file. The agreed transfer capability does not promise that every
supported format can be understood or generated by every runtime.

## Privacy, retention, and abuse requirements

- Only the signed-in conversation owner can preview or download files,
  including old versions. Anonymous users and other accounts are denied.
- No automatic expiry while the Ally exists. Internal access URLs may expire
  only if the product can obtain fresh authorized access to the same version.
- Deleting the Ally deletes its uploaded files and shared versions under the
  Ally deletion contract.
- File contents, credentials, and private storage locations must not appear
  in logs or public product events.
- Engineering must enforce file size/type validation and safe preview handling.
  HTML, code, and document active content must not execute merely because a
  file was uploaded, previewed, or downloaded.
- Rejected files must produce a clear failure without silently dropping them
  from a message.
- Temporary uploads that never become delivered files need bounded cleanup;
  cleanup must preserve the agreed retry and draft recovery behavior.
- Aggregate storage controls and malware-inspection policy require engineering
  review before release. They must not silently introduce expiry or alter
  the accepted product limits.

## Dependencies

- CLD-004 message lifecycle and idempotency contract.
- CLD-005 Cloud/Foundry integration boundary.
- Existing Foundry file access and durable workspace behavior, to be inspected.
- DSN-002 and the current Figma conversation/retry designs.
- The four delivery tickets implementing this shared scope.
- Ally deletion behavior for access revocation and cleanup at release.

## Open questions

The product scope is approved by Timi on 2026-09-08. No open product decisions block planning.

Engineering planning must resolve the exact extension list within the accepted
categories, safe-preview and malware-inspection approach, temporary-upload
cleanup, and aggregate storage protections. These are not permission to change
the agreed retention, limits, or user experience; surface a conflict if the
implementation cannot meet them.

## Acceptance criteria

- [ ] On web and mobile, Photos, Camera, and Files lead to appropriate selection;
      selecting alone does not upload.
- [ ] Supported files respect the 25 MB / 10 files / 50 MB defaults.
- [ ] Send displays per-file upload progress and delivers all files with optional
      text together, once, to the correct Ally.
- [ ] Later messages wait behind the uploading message; other Allies continue.
- [ ] A failed file marks the message failed; retry/removal preserves successful
      uploads and the user explicitly retries sending.
- [ ] Cancellation prevents delivery and restores editable text/file selections.
- [ ] Switching Allies preserves activity; interrupted uploads retain a retryable
      unsent message after return.
- [ ] An Ally can use an incoming file later, or plainly explain that it cannot
      read it.
- [ ] An Ally can return a newly created or existing file without losing its
      working copy.
- [ ] Every returned link preserves its sent version despite later edits.
- [ ] Both directions use the modal preview/download behavior for the agreed
      formats and the download-only fallback for other supported formats.
- [ ] Failed return delivery can retry the existing file without a broken link
      or unnecessary regeneration.
- [ ] Only the signed-in owner can open or download files.
- [ ] Old shared versions remain available while the Ally exists; deleting the
      Ally removes access and the files under the deletion contract.
- [ ] A cross-repository proof demonstrates these behaviors without leaking
      private file content or credentials.

## Engineer handoff

After claiming the ticket, the engineer and their agent must:

1. inspect the current repository and applicable repository instructions;
2. reconcile the specification with implemented behavior and accepted Nabu decisions;
3. create a reviewable implementation plan covering approach, files,
   sequencing, migrations, tests, risks, and verification;
4. obtain the required plan review or approval before implementation;
5. update the specification only if implementation reveals a genuine contract
   or product decision change.


## Source: projects/allies/delivery/now.md
Revision: 28a625d9ac623c82a3087003322dc7c40777d0891df2e9df31ae92b0dbac17c6

# Now

Canonical Nabu delivery state: `projects/allies/delivery/now.md`.
Feature map: `projects/allies/delivery/feature-map.md`.

## Current epic

`EPIC-03` — M3 Beta product surfaces.

The internal alpha is complete. People can create Allies, talk to them, switch
between them, reconnect, and retry safe failures. Beta now carries file
attachments, active-execution stopping, settings, responsibilities, and routines.

**Product owner:** Timi
**Design owner:** Ralph
**Active assignees:** None

## In progress

None.

## Recently completed

- `EPIC-02` — all 19 internal-alpha tickets are complete and owner-accepted.
- `DSN-001`, `DSN-002`, and `DSN-003` — the Workspace, conversation, Activity,
  and Ally animation designs are complete; `DSN-004` records combined approval.
- `CLD-006` — replay, signed cursors, reconnect, retry lineage, and
  stale-execution recovery are shipped and accepted.

## Beta backlog

- `CLD-010` — approved file-sharing scope; Design: `DSN-008`, Foundry: `FND-011`, Interface: `INT-106`.
- `CLD-011` — Cloud active-execution stop lifecycle.
- `FND-010` — Foundry runtime cancellation and acknowledgement.
- `INT-105` — web and mobile Stop controls and product states.
- `DSN-005` and `DSN-006` — Ally and global settings surfaces.

## Ongoing checks and blockers

- Continue performance, deployment-value, approval-continuation, and device retests.
- `CLD-009` and `INT-008` remain blocked on native staging and device acceptance.
- These checks remain visible, but they do not reopen the completed internal-alpha milestone.

**Canonical reconciliation:** 2026-09-08 Europe/Berlin.


## Source: projects/allies/delivery/tickets/foundry/FND-011.md
Revision: 890285542660b004c0af9e65953eca11ec0dbd4dd9133b2f20747f9a475bece5

---
id: FND-011
title: Receive and return files for Ally work
status: backlog
epic: EPIC-03
track: Foundry
owner_team: Foundry & Cloud
owners: [Timi, Holyworth]
repositories: [allies-foundry]
depends_on: [CLD-010, FND-007]
assignee: null
canonical: projects/allies/delivery/tickets/foundry/FND-011.md
local_copy: roadmap/board/epics/03-useful-responsibility-mvp/tasks/FND-011-ally-file-transfer.md
spec: projects/allies/engineering/specs/cld-010-user-message-file-attachments.md
feature: Send and receive files
product_stage: M3 — Beta product surfaces
workflow: kickoff
updated: 2026-09-08
---

# Receive and return files for Ally work

## Outcome

The intended Ally can use received files and return existing or newly created files without losing its working copy.

## User stories

- As a user, I can ask my Ally to work with a file I sent earlier.
- As a user, I can receive an existing or newly created file from my Ally.

## Deliverables

- [ ] Integration making accepted incoming files available only to the intended Ally under the Cloud contract.
- [ ] File-return capability publishing a specific version of an existing or newly created working file and obtaining its user-facing reference.
- [ ] Retry behavior resending the existing version after publication failure without regenerating it or publishing a broken link.
- [ ] Continued working-file access across later turns and the existing workspace continuity boundary.
- [ ] Tests and sanitized evidence for isolation, retry, fixed versions, later reuse, and deletion integration.

## Acceptance

- [ ] The Ally can use an incoming file in a later turn or explain that its contents cannot be read.
- [ ] Returning a file preserves the working copy and earlier shared versions.
- [ ] Failed publication can retry without recreating the file.
- [ ] Foreign Workspace/Ally files and private credentials are not exposed.

## Evidence

Attach merged PRs, relevant tests, and sanitized acceptance evidence before closing.

## Specification and dependencies

[[projects/allies/engineering/specs/cld-010-user-message-file-attachments|Approved file-sharing specification]].

CLD-010 must publish the transfer contract before implementation pickup. Planning may inspect current Foundry behavior earlier.


## Source: projects/allies/delivery/tickets/interface/INT-106.md
Revision: 6d7daa8489e63d1803ff27ccda8e5c14032838b282f1e1dd95eda1eeed409fb5

---
id: INT-106
title: Send, preview, and download files on web and mobile
status: backlog
epic: EPIC-03
track: Interface
owner_team: Interface Web & Mobile
owners: [Shapati, Abimbola, Tolani, Panda]
repositories: [allies-interface]
depends_on: [DSN-008, CLD-010]
assignee: null
canonical: projects/allies/delivery/tickets/interface/INT-106.md
local_copy: roadmap/board/epics/03-useful-responsibility-mvp/tasks/INT-106-file-sharing-web-mobile.md
spec: projects/allies/engineering/specs/cld-010-user-message-file-attachments.md
feature: Send and receive files
product_stage: M3 — Beta product surfaces
workflow: kickoff
updated: 2026-09-08
---

# Send, preview, and download files on web and mobile

## Outcome

Web and mobile implement the approved file-sending, preview, download, and recovery experience.

## User stories

- As a user, I can send files without text and continue using other Allies during upload.
- As a user, I can retry failed uploads and open sent or received files later.

## Deliverables

- [ ] Photos, Camera, and Files selection with 25 MB per file, 10 files, and 50 MB per message validation.
- [ ] Uploads beginning only after Send, per-file progress, ordered later messages, retry/remove, and cancellation restoring the draft.
- [ ] Uninterrupted uploads when switching Allies and retryable unsent messages after app interruption, including file reselection when needed.
- [ ] File links opening the approved preview/download modal in both directions, with owner authorization and safe rendering.
- [ ] Returned-file failure/Retry controls consuming Cloud's contract.
- [ ] Web/mobile tests and a full Interface → Cloud → Foundry file round-trip demonstration.

## Acceptance

- [ ] No message overtakes an earlier uploading message to the same Ally.
- [ ] Retry preserves successful uploads and explicitly resends the message; cancellation prevents delivery.
- [ ] Images/PDFs/text/Markdown/code preview safely; other supported formats offer Download.
- [ ] Old file versions remain accessible to the owner and no anonymous/foreign access succeeds.
- [ ] Final integrated proof includes FND-011, upload failure, publication failure, and later retrieval.

## Evidence

Attach merged PRs, relevant tests, and sanitized acceptance evidence before closing.

## Specification and dependencies

[[projects/allies/engineering/specs/cld-010-user-message-file-attachments|Approved file-sharing specification]].

DSN-008 and CLD-010 are implementation dependencies. FND-011 is a release/integration dependency; client implementation can proceed against the published contract.
