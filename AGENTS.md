# Agent instructions

These instructions apply from the repository root. Read any nested `AGENTS.md`
before changing files in its subtree; nested guidance is additive.

## Start here

- For Allies product, architecture, roadmap, specification, or planning work,
  connect to Nabu first. Read `projects/allies/index.md` and the relevant
  canonical notes. Nabu is the source of truth for evolving Allies knowledge.
- Use the installed Nabu skill and authenticated API. If Nabu is unavailable,
  do not silently substitute local notes; report the blocker.
- Never expose Nabu credentials, cookies, tokens, invite URLs, or private data.
- Read `ENGINEERING_STYLE.md` before changing code, writing a plan, or reviewing
  a change.
- If Nabu, local documents, and code disagree, identify the mismatch and do not
  silently rewrite one to match another.

## Plans and specifications

- For implementation plans, read and use
  `docs/templates/PLAN_TEMPLATE.md`. Do not use a generic planning template.
- Keep plans under `docs/plans/` as matching files:
  `docs/plans/<slug>.md` and `docs/plans/<slug>.html`.
- Keep Markdown and HTML synchronized. Move misplaced plans into `docs/plans/`
  rather than creating competing copies elsewhere.
- Keep product/engineering specifications separate from implementation plans.
  Use Nabu's canonical `projects/allies/engineering/specs/spec-template.md`.
- For plan HTML and other visual review artifacts, read
  `https://vercel.com/design.md` first. Use it for composition, hierarchy,
  typography, responsive behavior, evidence, and accessibility—not Vercel
  branding. Apply Allies colors and identity.
- Before implementation, inspect this repo's README, Makefile, CI, and test
  configuration. Record the exact checks used in the plan.

## Comments

- Default to no comments; clear identifiers should explain the code.
- Add a comment only when the WHY is non-obvious: a hidden constraint, subtle
  invariant, or workaround for a specific bug.
- Keep comments to one short line. Put longer rationale in the commit message
  or pull request description.

## Validation

- Run the smallest relevant check after each meaningful phase and the complete
  relevant validation before handoff. Do not claim a check passed unless it ran.
- Foundry quick checks: `make check`, `make validate`, `make lint`, and
  `make test APP=<path>`.
- Use `make format` for formatting when the change requires it.
- Prefer the locked `uv` toolchain and existing repository targets.

## Commit co-author policy

- Commits with material AI-agent help must include a `Co-authored-by:` trailer.
- Use one trailer per materially contributing agent:
  - `Codex <codex@openai.com>`
  - `Claude <81847+claude@users.noreply.github.com>`
  - `Cursor Agent <199161495+cursoragent@users.noreply.github.com>`
  - `Devin AI <158243242+devin-ai-integration[bot]@users.noreply.github.com>`
  - `gemini-code-assist[bot] <176961590+gemini-code-assist[bot]@users.noreply.github.com>`
- Add trailers only for agents that materially contributed to the commit.

## Git workflow

- Substantial implementation from an approved plan starts on a feature branch
  and opens a PR into `dev`; follow `CONTRIBUTING.md` naming (`ft/`, `fix/`, or
  `hot/`).
- Do not create a branch for every small fix or documentation chore unless the
  user asks for one.
- Keep commits focused and inspect status and the diff before committing.
- Never push directly to `dev` or `main` unless the user explicitly authorizes it.
