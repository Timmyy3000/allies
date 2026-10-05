# Track A: per-turn token burn

## Scope

Long sessions burn ~400KB (~100K tokens) per turn: 41.4M input vs 355K
output over 7 days, all `gpt-5.6-luna`, exhausting the 500K TPM budget
while replies stay small. Worker→gateway is already tight (16KB message,
bounded manifest). The burn is gateway-side transcript replay: full
history plus full tool outputs, compacted never (batch threshold is 50%
of a 1.05M window; micro-compaction off).

Non-goal: changing the continuity promise (no truncation, rotation, or
forking of the one conversation). Non-goal: gateway upstream forks.

## Approach (revised after adversarial + simplicity review)

0. Sequence gate: steps below run in order; 2–4 need step 1's numbers.
1. Measure from the gateway, not the worker: per-turn token usage
   (input/output/cached) as reported gateway-side. Worker byte counting
   is implemented as a labeled fallback proxy (request/response bytes on
   the hermes_stream observability pair), not the accounting backbone.
   No durable schema change yet.
2. Diet: cap tool-output persistence into the transcript gateway-side;
   confirm file re-staging stays manifest-only. (Worker already sends a
   bounded manifest; message capped at 16KB.)
3. Compact, cheapest effective first: add an absolute
   `compression.threshold_tokens` cap (100K, from the observed
   terminal-event failure boundary) to the profile seed, template, and
   legacy upgrade path, so batch compaction fires long before the
   50%-of-1.05M default. Small sessions never reach it: zero behavior
   change for them, cache intact between rare stalls. Escalate to
   micro-compaction only if measured occupancy still climbs. Batch and
   micro both keep user messages, head, and tail verbatim; no
   truncation, rotation, or forking, ever.
4. Sanitize: strip provider internals (project/org IDs, raw tracebacks)
   before failure text reaches chat. (Dropped from this plan: worker-side
   429 retry — the gateway already retries 3x; the worker never sees HTTP
   429. Gateway retry knobs only if verified to exist.)

## Affected surfaces

- `runtime/allies_runtime/profile_store.py`: seed field, template
  section, legacy manifest/config upgrade, fingerprint parity.
- `backend/runtime/services/profiles.py` + migration `0030`: seed
  field, strict default, fingerprint block, legacy backfill with
  materialization reset.
- `runtime/allies_runtime/hermes.py` + `observability.py`: byte totals
  on hermes_stream events (labeled proxy, not token truth).
- Rollout: backend deploy migrates seeds; image release carries worker
  + template; warm workspaces re-materialize on wake via the legacy
  upgrade path (precedent: memory migration 0024). No API changes.

## Affected surfaces

- Gateway usage reporting (source TBD: run telemetry vs log scrape;
  worker bytes are fallback only).
- Gateway profile config provisioning (micro-compaction flags need an
  owner — nothing writes profile `config.yaml` today; options are
  extending provisioning or patching gateway defaults, TBD before
  execution). Batch threshold uses the same surface.
- Cloud projection (failure-text sanitization point TBD — locate where
  provider error text becomes reply content during implementation).
- Rollout: supervisor-side changes ship via runtime image release;
  Railway-side via backend deploy. Name the vehicle per changed file.
  No API/schema changes in step 1; DB columns deferred to quota work.

## Acceptance

- Every turn emits input/output byte totals; Hanz-class turn totals
  visible without DB access.
- Micro-compaction absorb lines appear in gateway logs with occupancy
  flat across a 50-turn session; batch compactions stay at zero.
- Provider error text never reaches chat content; 429 triggers bounded
  retry, not immediate failure.
- Long-session replies keep completing; user messages stay verbatim
  (asserted in tests where behavior is ours).

## Validation

- Targeted: worker telemetry unit tests; compaction absorb log asserted
  on a fixture session.
- Integrated: `make runtime-test`, `make runtime-lint`; live Hanz-class
  session shows flat occupancy and no failed terminals.
- Reuse prior evidence where unchanged (event-cap fix, image pipeline).

## Risks

- Cache economics: rewriting history breaks the prompt-cache prefix;
  cadence choice must beat batch-only on measured spend, or stay batch.
- Summarizer model needs routing/keys (`auxiliary.compression`); latency
  lands at end of turn. Keep cadence modest until measured.
- Tool-output caps can hide information the user asked about; cap size,
  never drop silently — mark truncations.
- Upstream drift: gateway behavior changes under us; pin expectations to
  the deployed source SHA, not latest upstream.

## Unresolved decisions

- Exact transcript split (history vs tool outputs) needs a live session
  store read; estimates suffice to start, measurement gates the cuts.
- Durable per-turn accounting columns (quota backbone) deferred; file
  separately if quotas enter scope.
- Compression model choice and hosting for the summarizer.
- Sanitization point (Track B, allies-cloud): provider error text reaches
  chat as deltas; Cloud projection scrub is the leading option.
