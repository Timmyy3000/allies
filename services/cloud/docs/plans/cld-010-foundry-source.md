Source: projects/allies/delivery/tickets/foundry/FND-011.md
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
