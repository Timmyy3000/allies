# Web conversation attachments

Timi approved the attachment UI and requested backend integration and an Interface PR. This is web scope, using the current dev base. Native UI is a separate delivery. Preserve the approved motion and existing routine controls.

## Contract and ownership

Cloud PR 40 at 857b4f3 owns reservation, inspection, queue ordering, private access, cancellation and publication recovery. Foundry PR 54 at 51bdf24 consumes the accepted manifest. Interface talks only to Cloud's public API. The owner subsequently accepted default-on backend flags with explicit false shutdown overrides; release verification and deployed configuration remain separate. No deployment or merge is authorized here.

Use the existing session adapter for credentials, CSRF and cancellation. File send reserves a message through file-messages with stable client IDs, SHA-256 hashes and an idempotency key, uploads bytes through scoped content endpoints, and observes conversation file preparation. Failed files require explicit retry; successful uploads remain. Recovery and cancellation use current revision and generation fences.

## Implementation

1. Add validated file transport and message/publication mapping in cloud-client. Match Cloud's decimal 25 MB / 50 MB limits and extension allowlist.
2. Extract the approved picker and thumbnail motion into production components. Device selection and camera capture create local Files only. Reuse the existing chat frame.
3. Persist outgoing manifests and blobs in IndexedDB before admission; maintain uploads outside the per-Ally view so navigation does not abort work. Queue admission remains ordered with the existing text queue. On refresh, retain pending work and require Retry; never infer delivery from upload completion.
4. Show per-file progress, retry, removal, cancellation and reselect recovery. Render private file metadata, safe image/PDF/text previews, downloads and publication retry in the conversation.
5. Validate transport and lifecycle boundary cases, existing composer/queue/routine tests, web typecheck/lint/build, and browser interaction. Open the web PR into dev with backend dependencies and deployment limitations.

## Safeguards and review

No private file bytes in localStorage, logs or URLs. IndexedDB records include user/workspace/Ally scope. Logout aborts requests through the session adapter. Unknown reservation acceptance retries with the same key. Unknown upload acceptance reconciles before a generation retry. Cancellation restores a draft only after Cloud confirms cancellation. HTML/code render as text, never active documents. Successful selection is not upload or delivery.

Retain the development-only preview for design review. No extra HTML plan is needed; the approved interactive preview supplies visual evidence. Use separate local correctness and simplicity passes without subagents in this side conversation. Tests focus on ordering, failure/retry, cancellation, validation, scoped retrieval and unchanged text behavior.

## Release and rollback

PR targets dev and requires matching Cloud/Foundry migrations, runtime image, storage and inspection configuration before live acceptance. Rollback removes the file entrypoint while preserving pending records for recovery. Deployed storage/inspection/TLS end-to-end proof remains required when a test deployment is available; mocked transport tests must be labeled.

## Review and validation evidence

The web delivery stays in one PR because the approved motion, reservation adapter, queue recovery, and private viewer form one usable flow; splitting UI from recovery would expose an incomplete sending path. Generated OpenAPI changes are separate from authored code.

Correctness review fixed interrupted-send resumption, hidden unclaimed file messages after refresh, stale contract responses clearing files, cancellation racing an active upload, lost cancelled drafts, and raw-upload generation mismatches. Simplicity review retained the existing session/queue/query infrastructure, one transfer manager, browser IndexedDB, and no new runtime dependencies. Storage is limited to 64 saved transfers / 250 MB per browser and 10 per Ally; browser storage quota can be lower. Completed transfers are removed locally when observed as claimed or terminal; server retention is unchanged.

Cloud PR 40 advanced to 4808a53 after the inspected 857b4f3 export. The intervening diff changes configuration defaults and tests, not the public file/chat contract. No backend edits are included here.

Known release boundaries: native mobile implementation is separate. Camera capture needs HTTPS or the device-picker fallback. Cloud file IDs open in the authorized conversation modal; standalone copied /files/UUID navigation has no owner/Ally resolution endpoint in the current Cloud contract and is not implemented as public sharing. Production storage, scanner and TLS roundtrip must be verified on a matching deployment.

Validation on the delivery tree: 137 cloud-client tests; 208 web chat/file tests; six production-browser checks across desktop/mobile for send, private preview, retry after refresh and cancellation recovery. Root typecheck (web/mobile/client), web production build, cloud schema verification and web lint passed (48 warnings, zero errors). Browser Cloud responses were mocked; real request preparation, CSRF, raw XHR upload, SHA-256 and IndexedDB ran in Chromium. The routine fixture checksum initially failed only because Windows checkout converted its canonical LF bytes to CRLF; restoring canonical fixture bytes passed without changing its tracked contents.
