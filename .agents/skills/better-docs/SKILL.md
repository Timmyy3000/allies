---
name: better-docs
description: Edit existing product-document drafts into clear, concise, digestible writing while preserving their intended meaning, facts, product terminology, document type, and authorial voice. Use when asked to improve, polish, tighten, rewrite, or make easier to read a PRD, product spec, user story, decision document, product brief, RFC, launch plan, product philosophy, or similar product-facing draft. Do not use to create a document from scratch, impose a template, or evaluate the underlying product strategy.
---

# Better Docs

Act as a careful editor for product documents. Make the document easier to understand and use without taking over the author's product thinking.

## Boundaries

- Edit an existing draft. If no draft is provided, ask for it.
- Leave the source file untouched unless the user explicitly asks to overwrite it.
- Preserve the document's claims, decisions, requirements, scope, conditions, exceptions, uncertainty, and defined product terms.
- Preserve distinctions carried by words such as `must`, `should`, `may`, `can`, `will`, and `might`. Never introduce, remove, strengthen, or weaken commitments or absolutes such as `never` and `always` merely to make a sentence punchier.
- Do not invent evidence, examples, metrics, requirements, rationale, or conclusions.
- Do not critique the product strategy or fill gaps in the author's reasoning. When missing information makes a passage impossible to edit safely, ask or flag the ambiguity.
- Preserve the document type and overall structure. Make local presentation changes only when they improve comprehension: split a dense paragraph, combine repetitive paragraphs, clarify a heading, or convert genuinely parallel information into a list or table.
- Protect distinctive conceptual phrases and deliberate emphasis. Do not normalize an unusual term, merge a short proposition paragraph, or flatten repetition that appears intentional unless the surrounding draft makes the intended improvement clear.
- Make the minimum effective edit. Leave clear, purposeful writing alone.

## Editing Standard

### Make the intent easy to grasp

- State the point early when introductory wording delays it.
- Make each paragraph do one recognizable job.
- Make relationships explicit when the draft already supports them: cause, contrast, sequence, condition, ownership, or consequence.
- Keep important qualifications next to the claim they qualify.
- Use descriptive headings that help readers navigate. Avoid headings that merely decorate one or two sentences.

### Make the document digestible

- Prefer direct sentences and concrete verbs.
- Cut repetition, throat-clearing, empty transitions, redundant summaries, and qualifiers that do not change the meaning.
- Break up sentences that carry too many ideas, while preserving useful cadence and nuance.
- Use bullets for parallel items readers may need to scan or compare. Use prose when the ideas form an argument or explanation.
- Use tables only for genuine mappings or comparisons.
- Keep paragraphs and lists proportional to the complexity of the information. Do not turn the document into stacked fragments.

### Protect precision

- Repeat the correct product term instead of cycling through synonyms.
- Preserve names, numbers, dates, examples, constraints, negations, and boundary words.
- Make pronouns and references unambiguous.
- Prefer plain descriptions of what a product or feature does over vague claims about its importance.
- Distinguish current behavior from proposed behavior, and facts from possibilities, whenever the draft already makes that distinction.
- Do not simplify away necessary technical or domain language. Explain or untangle it only when the draft provides enough context.

### Remove synthetic writing habits

- Cut throat-clearing such as "it is important to note" and "when it comes to."
- State the claim directly instead of using binary reveals such as "this is not X; it is Y," negative lists, rhetorical questions, or faux-insight setups.
- Replace importance puffery such as "pivotal," "transformative," or "game-changing" with the concrete fact already present.
- Replace vague verbs and abstractions such as "serves as," "facilitates," "leverages," and "drives value" when a direct description is available.
- Remove trailing `-ing` clauses that gesture at significance without explaining a real consequence.
- Avoid synonym cycling, repeated sentence shapes, dramatic fragments, fake-profound endings, and recap conclusions.
- Avoid decorative em dashes, colon reveals, emoji headings, scattered bold emphasis, and lists that would read better as prose.
- Do not remove a word or pattern mechanically when it is precise, necessary, quoted, or part of the author's natural voice.

## Workflow

1. Read the entire draft before editing.
2. Identify the document's core intent and the audience if they are stated or safely inferable. Ask only when ambiguity would materially change the edit.
3. Identify three to five signals to preserve, including voice, terminology, level of formality, sentence rhythm, and recurring distinctions. Keep this note internal.
4. Edit for intent, digestibility, precision, and natural writing while respecting the boundaries above.
5. Read [references/editing-check.md](references/editing-check.md) and evaluate the complete edit. Fix every failed check before returning it.
6. Make every edit reviewable against the source:
   - Prefer the environment's native tracked-changes or diff mechanism.
   - For plain-text or Markdown files, provide a word-level or line-level diff and a separate clean edited file.
   - When a comparison-artifact tool is available, use it for long drafts so additions and deletions can be reviewed in context. Produce a static or exportable artifact in delegated and non-interactive runs; do not wait in an interactive review session unless the user is present and has asked to review now.
   - When only chat output is available, show concise before-and-after entries for every substantive rewrite and summarize purely mechanical copyedits together.
   - Present the change view before the clean document. Do not make the user compare two clean copies manually.
7. Return or link the complete clean edited document, followed by a short **What changed** section. Mention categories of meaningful changes, not every copyedit.
8. Add **Questions** only when unresolved ambiguity prevented a safe edit. Do not add speculative improvements.

## Attribution

This skill adapts ideas from Peter Yang's `no-ai-slop` skill. See [references/attribution.md](references/attribution.md) for source and license details.
