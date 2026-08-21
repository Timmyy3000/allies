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
- Treat Markdown and HTML as two complete presentations of the same plan.
  Markdown is optimized for agents; HTML is optimized for human review. The
  HTML may reorganize or visualize material, but it must preserve every claim,
  requirement, qualifier, contract, phase, acceptance criterion, test, risk,
  and open decision from the final Markdown. A concise opening summary is
  welcome, but it does not replace the complete plan below it.
- Keep both files synchronized after planning-worker, adversarial, simplicity,
  and user revisions. Build the HTML from the final edited Markdown, not an
  earlier draft. Move misplaced plans into `docs/plans/` rather than creating
  competing copies elsewhere; `.lavish/<slug>.html` is only the editable review
  artifact before the accepted HTML is exported to `docs/plans/<slug>.html`.
- Keep product/engineering specifications separate from implementation plans.
  Use Nabu's canonical `projects/allies/engineering/specs/spec-template.md`.
- Before asking for approval, edit the complete Markdown with `better-docs`,
  preserve a reviewable comparison and clean copy, then run the clean copy
  through `humanizer` without changing requirements or technical contracts.
- For plan HTML and other visual review artifacts, read
  `https://vercel.com/design.md` first. Use it for composition, hierarchy,
  typography, responsive behavior, evidence, and accessibility only. Never use
  the Vercel name, wordmark, triangle, logo, authorship shell, or Vercel-specific
  copy. The artifact must use Allies identity and may use Allies colors where
  they clarify state, structure, or evidence. The Vercel stylesheet and `vbg-*`
  primitives are implementation foundations, not permission to import Vercel
  branding.
- "No Vercel branding" means remove only identity markers; retain the design
  reference's visual system. Use the report foundation, `vbg-*` primitives, and
  page-owned `vbg-custom-*` hooks rather than replacing them with an unrelated
  minimal stylesheet.
- Use every matching Lavish playbook before writing HTML. Plans normally need
  `plan`, `diagram`, and `table`, with `comparison` or `code` when applicable.
  Dense mappings must be real semantic tables, and flows/lifecycles must be
  diagrams rather than literal Markdown syntax inside paragraphs.
- Before handoff, compare the final Markdown and HTML section by section, search
  the HTML for forbidden external branding, and run the Lavish browser layout
  audit. Layout success does not replace the content-parity or identity check.
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
