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

## Scope and authorization

- The user's explicit scope and applicable prior authorization take precedence
  over workflow defaults. Do authorized preparation and reversible work before
  asking for a material unresolved decision; do not ask again for permission
  already given. This does not waive engineering safeguards or access controls.
- A read-only or no-change request includes plans, memory, configuration, and
  knowledge records: report in chat unless the user authorizes writing artifacts.
- Use existing conventions and saved choices for routine mechanics. Treat new
  user input as a correction to the active task unless it clearly replaces it.
- If a skill blocks progress, cite its exact instruction, explain the concrete
  conflict, and continue independent authorized work. Do not invent approval gates.

## Plans and specifications

- Select the smallest route supported by scope and demonstrated risk. These
  route rules also govern the template, skill handoffs, and older local memory:
  - `tiny`: objective, 1–3 steps, acceptance checks, and rollback inline in the
    brief or response; no separate plan, HTML, or editorial pipeline.
  - `fast`: concise Markdown in `docs/plans/<slug>.md`; include scope, approach,
    affected surfaces, acceptance, validation, risks, and unresolved decisions.
  - `full`: use `docs/templates/PLAN_TEMPLATE.md` for the Markdown plan. Add
    `docs/plans/<slug>.html` when visual review helps resolve the work or the
    user requests it. Record whether HTML is needed once and pass that choice
    to workers; full planning alone does not require HTML. Markdown alone is the
    accepted plan when HTML is not required.
- Template examples illustrate format; they do not require new architecture.
  Include only relevant sections for fast work. Full plans retain the template
  headings and mark genuinely unchanged categories not applicable with a reason.
- When HTML is produced, treat Markdown and HTML as two complete presentations
  of the same plan.
  Markdown is optimized for agents; HTML is optimized for human review. The
  HTML may reorganize or visualize material, but it must preserve every claim,
  requirement, qualifier, contract, phase, acceptance criterion, test, risk,
  and open decision from the final Markdown. A concise opening summary is
  welcome, but it does not replace the complete plan below it.
- When HTML is produced, keep both files synchronized after planning-worker,
  adversarial, simplicity, and user revisions. Build the HTML from the final edited Markdown, not an
  earlier draft. Move misplaced plans into `docs/plans/` rather than creating
  competing copies elsewhere; `.lavish/<slug>.html` is only the editable review
  artifact before the accepted HTML is exported to `docs/plans/<slug>.html`.
- Keep product/engineering specifications separate from implementation plans.
  Use Nabu's canonical `projects/allies/engineering/specs/spec-template.md`.
- For full plans, before the required review or approval, edit the complete
  Markdown with `better-docs`, preserve a reviewable comparison and clean copy,
  then run the clean copy through `humanizer` without changing requirements or technical contracts.
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
- When HTML is produced, before handoff compare it with the final Markdown
  section by section, search the HTML for forbidden external branding, and run
  the Lavish browser layout audit. Layout success does not replace the content-parity or identity check.
- Before implementation, inspect this repo's README, Makefile, CI, and test
  configuration. Record the exact checks used in the plan.

## Comments

- Default to no comments; clear identifiers should explain the code.
- Add a comment only when the WHY is non-obvious: a hidden constraint, subtle
  invariant, or workaround for a specific bug.
- Keep comments to one short line. Put longer rationale in the commit message
  or pull request description.

## Validation

- Run checks appropriate to changed behavior and complete required validation.
  Reuse results while the relevant content and environment are unchanged; rerun
  affected checks after fixes or integration. Do not claim a check passed unless
  it ran. Do not add tests that merely mirror implementation or wording.
- Tiny low-risk changes may use one focused review covering correctness and
  simplicity. Other changes keep separate simplicity and correctness passes.
  Preserve all required engineering-policy and security checks.
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
