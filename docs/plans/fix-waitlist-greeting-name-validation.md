# Fix greeting validation for common-word Ally names

Route: fast. Status: ready for review. HTML required: no; visual review adds no value to this focused backend change. Planning only; implementation and PR delivery belong to the caller.

## Objective and evidence

Accept the reported greeting for `ally_name="Quiz"`: “Hi, I’m Quiz. I can create a clear, engaging quiz for you. What topic and difficulty would you like?” The current validator removes recognized self-introductions, then rejects every remaining whole-word name match. The ordinary noun “quiz” consequently causes an availability error.

Inspected at Cloud commit `be30af3aaaea372b693716d2761b54d22d563728`, branch `fix/waitlist-greeting-name-validation`:

- `AGENTS.md`, `ENGINEERING_STYLE.md`, `README.md`, `Makefile`, `backend/pyproject.toml`, `.github/workflows/ci.yml`, and `.agent/kickoff.yaml`: planning, validation, and delivery conventions. No nested `AGENTS.md` was found. The referenced `CONTRIBUTING.md` is absent; use the root instructions' `fix/` branch and `dev` PR conventions.
- `backend/waitlist/services/generation.py`, `backend/waitlist/tests/test_generation.py`, `backend/waitlist/services/entries.py`, and `backend/waitlist/tests/test_entries.py`: rejection, exception translation, persisted greeting, retry, and test behavior.
- `backend/allies/services/onboarding.py` and relevant existing patterns in `backend/allies/tests/test_api.py`: the same validator also gates production onboarding before `OnboardingAttempt` persistence. A repository-wide caller search found these two production callers.
- `backend/waitlist/providers/beta_greeting_policy.md` and `openai.py`: the provider already receives an explicit instruction that the selected name belongs to the Ally, plus truthful-capability and untrusted-profile instructions.
- Nabu `projects/allies/index.md` and accepted `projects/allies/engineering/specs/waitlist/CLD-008-cloud-waitlist-draft.md`: bounded generation, untrusted-output validation, truthful capabilities, privacy, and idempotent persistence remain binding. The canonical spec does not require a name-occurrence rejection. No canonical note was changed.

## Approach and scope

Remove the name-occurrence heuristic completely from the shared validator. Correct self-identification remains a provider prompt requirement; a repeated name token is not reliable evidence of misaddressing. Do not replace it with a vocabulary allowlist, more salutation regexes, another model call, retry loop, or dependency. This follows the requested Ponytail full/minimal approach.

Keep the existing `validate_output(value, *, ally_name="")` signature for this focused fix so both callers remain unchanged; document in the PR that `ally_name` no longer controls rejection. Preserve string trimming and the exact rejection behavior for non-string, blank, excessive-length, NUL, `<`, `>`, false resource claims, and preview framing. Keep `re`, which the remaining safety expressions still use. Prompt text, policy version, API schemas, storage, authorization, throttles, provider budgets, and exception handling need no change.

Expected implementation surfaces: `backend/waitlist/services/generation.py`, the two cited waitlist test files, and `backend/allies/tests/test_services.py` for a focused onboarding regression. No migrations or client changes.

## Execution steps

1. Add the exact Quiz regression to the validator tests and prove it fails on the current implementation. Include a small second common-word example or case variant to establish that acceptance is not a Quiz-specific exception. Retain self-introduction and substring acceptance coverage.
2. Delete only the name-dependent rejection block. Replace the old unit expectation that `Hola, Roban!` raises with an explicit acceptance case documenting that name-based style enforcement is now prompt-owned. Keep existing false-claim and preview tests; add a compact parameterized guard test for non-string, blank, configured length overflow, NUL, and both HTML delimiters, plus length-limit acceptance.
3. Replace the waitlist misaddressing integration case with a provider returning the exact Quiz greeting. Assert the returned and stored text match, the generation claim is cleared, and a repeated identical attempt returns the stored result without a second provider call. Retain an invalid-output integration case using a false resource claim to prove rejection still stores no greeting and surfaces `GenerationUnavailable`.
4. Add one focused `begin_onboarding` regression using the existing test settings/provider pattern: name Quiz, exact reported greeting, returned text and persisted `OnboardingAttempt.greeting` equal the provider text. Run the focused and repository checks below; review correctness and simplicity separately, then have the delivery owner prepare the authorized small PR into `dev` with the behavior tradeoff and test evidence.

## Acceptance and validation

- Exact Quiz text and other ordinary common-word reuse are accepted unchanged except existing outer whitespace trimming through the shared validator and both persistence paths.
- All unrelated safety rejection categories above remain enforced; invalid waitlist output still produces the existing failure and no stored greeting.
- Existing self-introductions, API contracts, retry identity, admission release, trusted-origin checks, and provider input minimization retain their behavior.
- No model/network calls are required for regression tests; injected providers exercise the deterministic failure boundary.

From repository root, after using the locked toolchain (`uv sync --locked` in `backend` if needed):

```text
make test APP="waitlist/tests/test_generation.py waitlist/tests/test_entries.py allies/tests/test_api.py"
make test APP=waitlist/tests
make check
make lint
```

Run `uv run ruff format --check` on changed Python files from `backend`; use repository formatting convention if changes require formatting. If `make` is unavailable on Windows, run its exact underlying commands from `backend`: `uv run pytest <same paths>`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`, and `uv run ruff check .`. CI remains responsible for its complete configured suite, lockfile, formatting, migration, coverage, and PostgreSQL checks; do not bypass required checks. Record unavailable checks and their concrete environment blocker rather than claiming success. No tests have been run by this planning worker.

## Risk, rollback, and open decisions

The deliberate tradeoff is that a provider may directly address a visitor by the Ally's name and still pass the hard validator. The prompt continues to forbid this identity confusion. This is a style-quality risk, accepted by the requested removal of the overbroad check; it is not a reason to weaken the retained safety guards. Revisit only with concrete recurrent misaddressing evidence and examples that distinguish it from normal language.

Rollback is a normal revert of this focused implementation and test commit through the standard PR process. No data migration or data deletion is needed; existing stored greetings remain valid. A revert restores the known common-word false rejection and should be reserved for a demonstrated more serious regression.

No unresolved product decision blocks implementation. Assumptions: the reported text is authoritative reproduction input; removal is permitted by the user's explicit scope; PR base is `dev` per repository policy unless the caller has a more specific authorized target. Deployment/promotion is outside this planning task. Retaining the currently unused keyword avoids unrelated caller churn and is not a new public compatibility promise.
