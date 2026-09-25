# Platform prompt layer — Phase 2 plan

## Scope

Split the Ally prompt into three layers: a user-editable soul (name, job, personality), an Allies-owned platform layer (shared rules, follow-through, voice, capabilities), and skills (unchanged). Existing Allies move to the slim soul, re-rendered from the name, job, and personality they were created with.

## Approach

- `runtime/hermes-image/PLATFORM.md` is baked into the image at `/opt/hermes/allies/PLATFORM.md`. The sandbox mounts `/` read-only, so the Ally cannot edit it.
- `patches/platform-layer.patch` appends the platform layer immediately after the soul in the stable prompt tier, so user-controlled soul text precedes the rules that bound it. When the platform layer is present it replaces Hermes' own docs pointer (`HERMES_AGENT_HELP_GUIDANCE`), which told Allies they "run on Hermes Agent". Its content is folded into the platform version marker from the prompt-compartment refresh, so edits reach live sessions on their next turn.
- `backend/runtime/default_allies_soul.md` keeps only identity, job, and personality.
- Migration `0032_platform_layer_soul` re-renders every stored seed whose personality is an exact rendering of the retired template (verified by re-rendering), updates the fingerprint, and requeues materialization, following `0030`. The runtime derives the retired rendering from the new seed (`allies_runtime/soul_upgrade.py`), accepts that fingerprint as an upgrade, overwrites `SOUL.md`, and updates the manifest. Hand-edited `SOUL.md` files on managed profiles are overwritten by owner decision (beta; the Ally cannot write `SOUL.md` today).

## Product decisions (Timi, 2026-09-25)

- Allies may set one-time follow-up routines on their own and say so in conversation; recurring routines still need a yes.
- An acknowledgement streamed before tool work and the final answer may share one reply.

## Validation

- `smoke_platform_layer.py` (image build): shipped file present, soul before platform, Hermes docs pointer removed, marker changes on platform edit, feature off without the file.
- Runtime: `tests/test_soul_upgrade.py` (exact-rendering derivation, upgrade overwrites `SOUL.md` and preserves profile state, unrelated personality change still conflicts, runtime template matches backend file).
- Backend: `test_soul.py` rewritten for the slim soul; migration probe covers managed upgrade, custom-seed skip, and rollback.

## Rollback

Reverse migration restores the retired rendering for upgraded seeds. A reverted image drops the platform layer; souls stay slim until the reverse migration and re-materialization run.

## Known limitations

- `SOUL.md` is mounted read-only for the Ally's tools, so conversational soul edits need the follow-up soul-editing work.
- Cloud concatenates streamed segments without a separator, so an acknowledgement and final answer can run together.
