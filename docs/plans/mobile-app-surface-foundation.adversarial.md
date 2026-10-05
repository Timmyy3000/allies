# Mobile App Surface Foundation Adversarial Review

## Verdict

Blocked before revision. The contract pin and five major state boundaries required correction before implementation.

## Findings

| Severity | Area | Finding | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| Blocker | Cloud contract | The old pinned contract did not contain the required onboarding, Ally, conversation, message, or activity paths. | The pin was dated 2026-08-17 and the generated client ended at Workspace context. | Refresh and verify every required path, header, parameter, and response before mobile implementation. |
| Major | Auth and first-run routing | The plan did not define behavior for every session state and route class. | The current root redirects every signed-in route to Account; session also has checking, refreshing, offline, and unavailable states. | Add a route/status matrix and deterministic tests. |
| Major | Onboarding creation | The plan did not define how the current local preview becomes the official Cloud attempt, greeting, auth handoff, and create flow. | Current preview has display props only, uses a local greeting, and keeps the reply inside the screen. | Add an explicit create-mode state machine with attempt timing, Cloud greeting, persistence, auth, expiry, retry, back, and cancel behavior. |
| Major | Mutation recovery and concurrency | Mutation-local idempotency could not recover from an unknown result after remount or restart. | The initial plan did not persist pending mutation identity. | Persist the exact command and key before OAuth or transport. Derive work state from Cloud after remount. |
| Major | Pagination, polling, and safe activity | The plan did not define overlap merge, conflict behavior, terminal strings, polling bounds, or the one safe activity copy field. | It specified sequence rendering and a neutral fallback only. | Define message ID dedupe and conflicts, active/terminal/unknown states, hard poll ceiling, focus/abort behavior, and `ActivityResponse.text` as the only activity copy. |
| Minor | Workspace bounds | Current-session reachable IDs could produce an unbounded group of reads. | The plan called the reads bounded without a number. | Display 12 IDs per user-selected page. Do not impose an Ally creation limit. |
| Minor | Acceptance and tests | The focused test command and high-risk test cases were not concrete. | The initial command used a path placeholder. | Name the test files and include timer, abort, overlap, remount, and route-state cases. |

## Finding Dispositions

| Finding | Disposition | Revision evidence |
| --- | --- | --- |
| Cloud contract | Accepted and resolved | Refreshed, generated, and verified the 2026-08-28 contract at SHA-256 `1fceace350f418f1371451356e4dcf5626259cf2148b36d2611c36dfb0ea3b4f`. The generated types now contain every required path. |
| Auth routing | Accepted | Added a complete route/session matrix for public, sign-in, callback, and protected routes. |
| Onboarding state | Accepted | Added the official `editing -> attempt -> preview -> auth -> create -> provisioning` state machine, Cloud greeting, retry, invalid-attempt, back, and cancel rules. |
| Unknown mutation outcome | Accepted | Added a bounded encrypted pending-command file. The client writes before OAuth or transport and retries the same body and key. Expo SecureStore holds only the AES key. |
| Conversation rules | Accepted | Added newest-first cursor semantics, ID dedupe, conflict rejection, ordered merge, allowlisted polling states, a ten-minute ceiling, focus/abort rules, and safe `text` rendering only. |
| Workspace bound | Accepted | Added 12-at-a-time display paging while retaining no product-facing Ally creation limit. |
| Tests | Accepted | Replaced the placeholder with named test files and high-risk deterministic cases. |

## Missing Questions Resolved

- The refreshed staging contract contains every required operation except an Ally collection read.
- Cloud resolves unknown create and send outcomes when the client repeats the exact body with the same idempotency key. The Interface therefore persists that command identity before transport.
- `ActivityResponse.text` is the safe product copy. Known active states are `queued`, `in_progress`, and `running`; `completed`, `failed`, and `stopped` are terminal; `awaiting_action` is paused; unknown values stop automatic polling.

## Confidence

High. The revision uses the refreshed generated contract, accepted Nabu lifecycle specifications, and current mobile source behavior.
