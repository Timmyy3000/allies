# Prompt compartment refresh — Phase 1 plan (rev. 2, post-adversarial review)

## Scope

Give live Hermes sessions a version-gated prompt rebuild so platform-config changes (platform hints, tool/procedure guidance) and soul content changes take effect on the next turn instead of freezing for the session's life. Soul *edit surface* is explicitly out (later episode); soul *version marking* rides along because it costs nothing extra in the same patch.

## Approach

Extend the existing stale-runtime gate instead of building a refresh system. Hermes already rejects a stored prompt when runtime identity drifts (`_stored_prompt_matches_runtime`); Phase 1 adds two version markers to that same decision. Steady state stays byte-identical; rebuilds happen only on actual change (rare by nature).

**Version sources (no new coordination):**
- Soul version = sha256 of the SOUL.md content Hermes already reads at build (`load_soul_md`). Content change ⟺ version change, no sidecar, no migration. A genuinely absent/empty SOUL is a distinct state from a read failure (ADV-004).
- Platform version = build-time file `/opt/hermes/.allies-prompt-config-version` (image digest inputs: `HERMES_SOURCE_SHA` + hash of the applied patch set) **plus** a hash of the profile's prompt-affecting config (`platform_hints` section) read at gate time. Image changes need no manual bumps; profile-hint edits are covered without an image rebuild (ADV-001). Both inputs fold into the single platform marker — no third marker.
- Feature activates only when the version file exists (Allies images). All other platforms behave byte-identically to today — zero upstream behavior change.

**Gate (beside `_stored_prompt_matches_runtime`, same choke point every caller routes through):**
- Missing or malformed markers invalidate a stored prompt whenever the version file exists — legacy markerless sessions rebuild once, then persist marked prompts (ADV-002).
- Markers are recognized only inside Hermes' own trailing timestamp block: parsing anchors on the last genuine block start and treats user-content forgeries (SOUL, memory, context files) as non-markers. A malformed trailing block fails closed to rebuild (ADV-003).
- SOUL read failure preserves the last-good prompt and retries next turn; only a genuinely absent/empty SOUL builds the default-identity prompt (ADV-004).
- Check runs at turn start only; in-flight turns never swap mid-turn.

**Rebuild:** full rebuild from current sources on mismatch (no splicing). Rebuild failure keeps the last-good prompt and retries next turn.

**Recorded exception (ADV-005, owner-confirmed 2026-09-25):** Allies accepts a scoped exception to Hermes' byte-stable-per-conversation prompt invariant: turn-boundary-only rebuilds on version change; mid-turn swaps prohibited; steady state stays byte-stable.

## Affected surfaces

- Hermes image overlay (`runtime/hermes-image/`): one new patch (gate extension + marker emission + read-failure distinction), one Dockerfile block (version file), one build-time smoke script plus one persisted-session lifecycle check. No Foundry backend changes. No Cloud changes. No Interface changes.

## Acceptance

- Platform-config change (image-baked hint edit, or profile `platform_hints` edit) takes effect on a live session's next turn after adoption, with no session reset.
- Soul content change takes effect on the next turn (proven by direct SOUL.md change in test, UI surface out of scope).
- With no layer changed, consecutive turns produce byte-identical prompts.
- Reverting the image does **not** auto-heal pre-feature sessions (corrected claim, ADV-006): newer prompts persist until natural session rotation/compression; the downgrade path is documented and bounded, not silent.
- Skills-freshness statement delivered with named evidence: prompt-baked skills index (`build_skills_system_prompt`) vs invocation-loaded bodies (`skill_view`); recorded in PR evidence (ADV-008).

## Validation

- `git apply --check` of the new patch against pinned `HERMES_SOURCE_SHA` in isolation.
- Build-time smoke (fixture prompts): marker match / soul mismatch / platform mismatch (image-sourced and config-sourced) / absent version file (behaves as today) / markerless legacy session (rebuilds once) / SOUL-forged anchors+markers (ignored, genuine block wins) / transient SOUL read error (last-good preserved).
- Persisted-session lifecycle check against a real temporary session store: persist prompt → change a layer version → restore on a new turn → verify rebuilt prompt is used **and** persisted.
- Downgrade check: newer-marked prompt under a pre-feature gate keeps working (no crash, no silent wrong behavior); recovery via natural rotation is documented.
- `make lint`; hermes-image CI (`Build and smoke-test runtime pair`) green on the PR.
- No backend code touched; full `make validate` stays green.

## Risks

- Marker shadowing by user content → anchored trailing-block parsing + dedicated forgery smoke case.
- Over-broad version (all patches bump) → accepted deliberately; documented, revisit only if release cadence makes per-session rebuilds frequent.
- Prompt-cache cost on rebuild turns → accepted; rebuilds are rare and version-gated.
- Residual (review-noted): any correct refresh still costs one prefix-cache miss on the changed layer.

## Rollback

Revert the PR and rebuild the image. Corrected expectation: sessions already carrying newer markers do **not** rebuild down under a pre-feature gate — they continue on their persisted prompt until natural rotation or compression rebuilds them. Bounded (session lifetimes are finite) and documented; no data loss, no stuck state. Forward-fix is preferred over downgrade for any urgent reversal.

## Unresolved decisions

- None blocking implementation. All review findings disposed; no re-review (revision tightens within the same architecture — validation strengthened, no scope or mechanism change beyond the folded config-hash input).
