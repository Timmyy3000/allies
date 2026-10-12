# Let allies read Gmail attachments

Route: fast. Playbook: bug fix. Grant: autonomous plus deploy (memory `deploy-every-fix`). The user said "just fix the bug" and "allow allies to download and view attachments to emails".

## Problem

`allies_gmail` `download_attachment` and `attachment_status` publish the attachment into Cloud private storage and return only a `chat_reference` link (`services/cloud/backend/integrations/services/gmail_attachments.py:119`). The bytes never reach the ally's workspace, so the ally cannot read the PDF. User-uploaded files work because they are staged into the workspace (`services/foundry/runtime/allies_runtime/files.py`). The tool description also never tells the ally to read an attachment when the question depends on its contents.

## Approach

Reuse the existing inspected publication. Once a Gmail attachment publication is `ready`, let the ally pull the inspected bytes into its own workspace.

1. **Cloud.** In the `ready` result, add `file_id` per file. Add an internal service-token endpoint, `GET /internal/v1/gmail-attachment-files/{file_id}/content?binding_id&message_id`. It streams a `READY` file only when that file belongs to a Gmail attachment publication of that message and binding. Mirror `accepted-files` content (headers, 404 on scope, 503 on storage).
2. **Foundry.** Add `GET /runtime/integrations/files/{file_id}/content`, authenticated by the same signed tool capability token that `call_integration_tool` uses. Resolve message and binding through `_dispatch_identity`. Routine runs are rejected. Stream from the Cloud endpoint above.
3. **Hermes tool (`allies_gmail.py`).** Add the `save_attachment` action with `publication_id`. It calls `attachment_status` through the existing relay. When the publication is ready, it streams each file through the Foundry endpoint into `<cwd>/email-attachments/<safe filename>`, capped at 25 MB, and returns the paths. The `pdftotext` instruction applies to PDFs, and the ally also gets the existing `chat_reference`. Update INSTRUCTION. When the user's question depends on an attachment's contents, download it, save it, and read it before answering. Do not ask the user to upload it.

## Acceptance

- An ally asked "does the attached PDF explain X" downloads the PDF, saves it, reads the text, and answers without user prompting.
- Files from another message, binding, or non-Gmail publication return 404.

## Validation

Cloud and Foundry pytest for touched modules (`test_gmail_attachments.py`, `test_integration_tools.py`), runtime `test_gmail_tool.py`. Then deploy via `/opt/allies/deploy` and repeat the screenshot scenario live.

## Risks

- Path traversal via filename. Sanitize to a basename and reject `..`.
- Large files. Cap the stream at the publication size.
