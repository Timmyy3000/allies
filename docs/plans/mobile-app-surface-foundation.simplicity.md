# Mobile App Surface Foundation Simplicity Review

## Initial Verdict

Needs decisions. The plan was sound, but five choices needed simpler and more precise dispositions.

## Findings and Dispositions

| Area | Finding | Disposition |
| --- | --- | --- |
| Pending command size | SecureStore is not suitable for the existing 4,000-character reply limit. | Keep the current input limit. Use the installed Expo Crypto AES-GCM API and FileSystem document directory for ciphertext. Keep only the AES key in SecureStore. Add no dependency. |
| M2 completeness | The Cloud contract cannot list all workspace Allies after restart. | Call this an M2 mobile slice. Show only Cloud-fetched Allies reachable in the current session. Record the exception in Nabu until Cloud adds the collection read. |
| Cloud client surface | A conversation-by-ID method was planned but no M2 screen needs it. | Do not add that client method. Add its path only to authenticated request classification. |
| Workspace paging | Page state and a paging abstraction are unnecessary for a small session list. | Use one `visibleCount` value. Load more adds 12. |
| Test seams | A general repository or service layer would add indirection. | Permit one small store factory that follows the existing secure session store pattern. Do not add a provider, repository, service, or navigation framework. |
| Command ownership | A pre-auth draft could otherwise cross account boundaries. | Use the existing account `userId` and workspace ID. Bind once before transport, expire after seven days, and clear on explicit sign-out. Do not add an account-command service. |

## Kept Complexity

- Keep the explicit route and session matrix because it prevents redirect loops and protects auth return.
- Keep stable idempotency records because they prevent duplicate Cloud work after unknown results.
- Keep message overlap checks because conflicting Cloud messages must fail safely.
- Keep bounded, focus-aware polling because it protects battery use and lifecycle correctness.

## Final Direction

The revised plan is lean enough to implement. It reuses installed Expo modules and current mobile patterns. It does not add a dependency or a speculative product surface.

## Final Re-review

**Verdict: LEAN.** The revised plan expires pre-auth commands after seven days, binds them to one authenticated user and workspace, clears them on mismatch or explicit sign-out, and keeps the HTML presentation synchronized with the Markdown plan.
