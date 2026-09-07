# Alpha speed benchmark results

**Date:** 2026-09-07  
**Evidence status:** implementation and local/real-Fly proof complete; not merged or enabled in production.

## Scope and measurement contract

The runs use local Docker Cloud/Foundry/PostgreSQL/Redis, HTTPS tunnels, fake OAuth, a real Fly machine in `ams`, and the real OpenAI `gpt-5.6-luna` path. The baseline Foundry control revision is `c5895914e7ff8d4d9655aea394af026bb4779b26`. The candidate uses Cloud `1be3a1c`, runtime `e9ead8a`, runtime image digest `sha256:278c2a0c186f7e9a3508b7100ea47c63d57d468ea7964395386142b9ed325545`, and Hermes digest `sha256:e7aa0fd7e36106f9805970d2d90d1894d106df14c3717d064c6a06aa358a5a03`.

All times below are seconds from the create request unless stated otherwise. `Ready` is the first client API poll that observed the Ally as ready. `First` is the first reply observed by the API poller. `Complete` is the completed reply observed by the API poller. `Flow` includes the preview/greeting and the 15-second simulated input where the intent scenarios used it. Polling used 250 ms intervals plus HTTP latency. These are API observations; browser paint and deployed-preview timing were not measured.

One cold sample and three awake/asleep samples are useful phase evidence, but they are not a controlled old/new experiment, a percentile study, or a production latency estimate. The asleep cases reused the same machine after it was verified stopped; they do not measure an automatic idle-stop policy.

## Baseline: seven runs

Source: `.tmp/alpha-benchmark-report.md`. The report's first timing column is **profile materialized**, which is a durable backend boundary and should not be read as the candidate client's `Ready` poll.

| Scenario | Profile materialized | Cloud provisioning confirmed | First reply | Reply complete | Greeting |
|---|---:|---:|---:|---:|---:|
| provisioning | 119.88 | 165.65 | 182.76 | 184.13 | 3.02 |
| awake-1 | 7.60 | 16.08 | 20.41 | 20.41 | 1.81 |
| awake-2 | 0.36 | 2.92 | 7.75 | 8.11 | 0.90 |
| awake-3 | 2.91 | 7.50 | 11.48 | 11.81 | 2.35 |
| asleep-1 | 15.53 | 40.62 | 55.89 | 57.20 | 1.32 |
| asleep-2 | 15.22 | 16.02 | 24.62 | 25.97 | 1.32 |
| asleep-3 | 16.22 | 45.26 | 57.46 | 59.70 | 1.75 |

The baseline medians stated by the report are **11.81 s** completed reply for the three awake runs and **57.20 s** for the three asleep runs. Cold provisioning has one sample. The cold path included Fly app/secrets/volume/machine creation, cold image preparation, runtime boot, profile materialization, retries, and the first response; Fly logs recorded 66.328 s of cold Hermes image preparation.

## Candidate measurements

Source: `.tmp/alpha-speed/measurements/alpha-benchmark-*.json` and the corresponding Cloud/Foundry snapshots. Values are shown to 3 decimals; source JSON retains more precision. The ordinary candidate rows used `activity_wait=true`, `readiness_hint=true`, and `ready_pool_target=0`; the ready-pool rows used `ready_pool_target=2` and Foundry revision `b0241bc`.

| Scenario | Ready | First | Complete | Flow | Greeting | Intent result |
|---|---:|---:|---:|---:|---:|---|
| candidate-cold-1 | 101.076 | 109.214 | 110.237 | 117.129 | 6.892 | not sent |
| candidate-awake-1 | 1.606 | 6.578 | 12.917 | 14.311 | 1.393 | not sent |
| candidate-awake-2 | 1.617 | 5.715 | 5.716 | 7.173 | 1.457 | not sent |
| candidate-awake-3 | 1.360 | 6.258 | 6.597 | 7.486 | 0.889 | not sent |
| candidate-asleep-1 | 17.831 | 25.517 | 25.831 | 27.179 | 1.348 | not sent |
| candidate-asleep-2 | 16.965 | 23.909 | 24.924 | 26.865 | 1.941 | not sent |
| candidate-asleep-3 | 22.330 | 90.580 | 94.900 | 95.848 | 0.949 | not sent |
| candidate-asleep-intent-1 | 136.175 | 203.417 | 204.599 | 220.366 | 0.723 | sent; request failed |
| candidate-asleep-intent-2 | 227.374 | — | — | — | 0.804 | sent; request failed; interrupted/unfinished |
| corrected-asleep-intent-1 | 128.101 | 210.141 | 211.483 | 228.417 | 1.870 | `rate_limited` |
| corrected-asleep-intent-2 | 193.708 | 267.560 | 268.915 | 286.575 | 2.580 | `waking` |
| corrected-asleep-intent-3 | 216.222 | 299.406 | 300.416 | 316.474 | 1.023 | `rate_limited` |

Exact candidate medians for the three ordinary awake rows are Ready **1.606159 s**, First **6.258486 s**, Complete **6.597107 s**, Flow **7.486263 s**, and Greeting **1.393490 s**. For the three ordinary asleep rows they are Ready **17.831162 s**, First **25.516857 s**, Complete **25.830778 s**, Flow **27.178681 s**, and Greeting **1.347846 s**. These medians describe the recorded candidate samples only; the asleep set contains the 94.900 s completion outlier.

The candidate cold row is one observation: Ready **101.076342 s**, First **109.213806 s**, Complete **110.236910 s**, and Flow **117.129222 s**. It is not comparable to the three warm rows as a sample-size or cache-state claim.

### Invalid intent and outlier handling

The first intent sequence is invalid for wake-latency proof. The Cloud log records a `409` on `POST /api/v1/onboarding/runtime-intents` at `2026-09-07T16:22:27.747Z`; the matching Foundry request returned `409` at `16:22:27.743Z`, and a later Foundry intent request returned another `409` at `16:24:22.278Z`. The harness recorded `creation_intent.failed=true` for `candidate-asleep-intent-1` and `candidate-asleep-intent-2`. Their subsequent profile/provisioning timings are retained for diagnosis, but the failed intent request is not counted as a successful wake proof.

`candidate-asleep-intent-2` has only a Ready observation at **227.374370 s**. Its saved Foundry snapshot still showed the execution as running and the attempt as running, with no First or Complete observation. It is retained as an interrupted/unfinished run, not imputed as a latency.

The corrected intent series used a 15-second simulated input. `corrected-asleep-intent-2` returned `waking` and completed at **268.914907 s**; this is the later ~268.9-second outlier. `corrected-asleep-intent-3` returned `rate_limited` and completed at **300.415943 s**; this is the later ~300.4-second outlier. `corrected-asleep-intent-1` returned `rate_limited` and completed at **211.482569 s**. The configured `ALLIES_RUNTIME_SPECULATIVE_START_COOLDOWN_SECONDS=300` explains the rate-limit status when `last_speculative_start_at + 300 s` had not elapsed. The benchmark did not change that policy. These three rows are serialized, mixed-status diagnostics rather than a matched control/candidate comparison.

## Readiness-hint handoff evidence

The matching Cloud/Foundry DB snapshots contain one generation-1 readiness hint in `delivered` state for each candidate row. The following representative rows show the handoff with database timestamps; the profile `updated_at` is the Foundry materialization boundary, followed by Foundry hint receipt/delivery, Cloud's `readiness_hint_received_at`, Cloud provisioning completion, and Foundry execution creation.

| Scenario | Profile updated | Hint occurred | Hint attempt start (legacy `delivered_at`) | Cloud hint received | Cloud provisioning completed | Execution created |
|---|---|---|---|---|---|---|
| candidate-cold-1 | 16:14:27.352 | 16:14:27.355 | 16:14:27.453 | 16:14:27.672 | 16:14:28.102 | 16:14:28.209 |
| candidate-awake-1 | 16:15:13.354 | 16:15:13.356 | 16:15:14.041 | 16:15:14.155 | 16:15:14.522 | 16:15:14.607 |
| candidate-asleep-1 | 16:17:49.026 | 16:17:49.029 | 16:17:49.488 | 16:17:49.691 | 16:17:50.077 | 16:17:50.164 |
| corrected-asleep-intent-2 | 16:46:17.388 | 16:46:17.391 | 16:46:17.443 | 16:46:17.737 | 16:46:18.369 | 16:46:18.555 |

These snapshots predate the local post-HTTP timestamp fix, which passed 14 tests. Under the captured pre-fix semantics, `readiness_hints.delivered_at` was populated from the pre-HTTP observed/attempt start, so it must not be interpreted as an acknowledgement time. The Cloud `readiness_hint_received_at` and `provisioning.completed_at` fields remain the valid handoff and completion boundaries for these artifacts. No post-fix timing measurement is inferred from these rows. The handoff is a backend timing record, not a browser paint measurement. The API `Ready` observation can occur later because it depends on polling, machine state, reconciliation, and the client-visible readiness contract.

## Startup pressure diagnosis

`.tmp/alpha-speed/candidate-resource-pressure.txt` preserves a host snapshot taken during the candidate series. Its raw `/proc/stat` line records `steal=26831` ticks, `idle=9294`, and `system=523`; CPU PSI `some avg300=18.69%`, `full avg300=0.00%`; memory PSI is zero; and `MemAvailable=585484 kB` of `MemTotal=985220 kB` with no swap. A parent capture from the same run derived about **68.35% cumulative CPU steal** (`26829 / 39251`); the raw counters are cumulative snapshots taken at different moments.

The evidence supports shared-host hypervisor scheduling contention as a strong contributor, but it does not prove it is the sole cause. The slow-start log also shows serial profile reconciliation and an exact 60-second Hermes startup-grace-shaped exit after the process had begun booting. The current evidence has no per-profile stage timing that can separate CPU steal from N-profile startup amplification. Optional activity waiting runs after initial reconciliation and is not enough evidence for the delay. A matched run with different CPU capacity is the next useful measurement. Fly documents shared-CPU burst balances and quota behavior in [CPU Performance](https://fly.io/docs/machines/cpu-performance/).

## Bootstrap helper proof

`bootstrap-helper-proof-3.json` is the corrected six-run batch: three interleaved control runs and three candidate runs. All six passed ownership checks, release metadata checks, pre-bootstrap secret staging, read-only helper-machine secret SHA verification, stopped-state verification, secret cleanup, and exact-app deletion.

| Variant | Runs | Median bootstrap | Median helper stop |
|---|---:|---:|---:|
| control (`/bin/sh -c 'sleep 1800'`) | 3/3 passed | 22,267.932 ms | 8,013.324 ms |
| candidate (`/bin/sleep 1800`, SIGTERM, 5 s) | 3/3 passed | 16,088.026 ms | 1,957.195 ms |

The raw median reductions are **6,179.906 ms** for bootstrap and **6,056.129 ms** for helper stop. Bootstrap includes the staged-secret probe, about 0.262–0.311 s per run; subtracting that probe per run gives median bootstrap times of **21,967.861 ms** control and **15,812.503 ms** candidate, a **6,155.358 ms** net median difference. The initial two batches used an invalid post-stop `fly secrets deploy` capability sequence and are retained as debug artifacts only; they are excluded from acceptance samples.

## Ready-pool proof

`pool-two-ready.json` at `17:19:39.184673+00:00` recorded two distinct ready bundles in `ams` with the target set to 2. Each had generation 1, start epoch 1, a blank-volume marker equal to its volume, zero profiles and executions, one active credential, and the same release fingerprint. The failed initial proof bundle was evicted and is not part of the success pair.

`pool-two-assigned.json` at `17:20:20.447344+00:00` shows the same two bundles assigned to two distinct Cloud tenants. For each bundle, the immutable internal workspace, app, machine, volume, generation, start epoch, and blank-volume marker were retained. Each assigned bundle has exactly one active credential, one profile, and one execution. The pool tenant reference changed to the Cloud tenant reference while the provider identity stayed bound to the original bundle.

| Assignment | Ready | First | Complete | Flow | Greeting |
|---|---:|---:|---:|---:|---:|
| ready-pool-a | 2.302736 | 9.570592 | 9.873266 | 11.784732 | 1.911426 |
| ready-pool-b | 2.000237 | 9.617446 | 9.943375 | 11.738325 | 1.794883 |
| two-run median | 2.151486 | 9.594019 | 9.908321 | 11.761529 | 1.853154 |

This is initial allocation evidence: the pool pays the app/machine/volume/release/image preparation cost during maintenance so a new assignment can observe readiness in about 2 seconds. It does not repair the earlier ordinary asleep measurements, whose workspaces were deliberately stopped and run with `ready_pool_target=0`; those 57.20 s and 94.900 s completions remain valid observations for that path. Assigned bundles leave the pool and are not returned after customer use.

The first empty-pool cold-fallback attempt failed at about **45.151 s** with `repair_required` after the existing provider terminal-404 classification while listing volumes. That classification and handling are byte-identical to the c589 provider files; the raw Fly cause is unknown, so this attempt is not a successful fallback sample. The second real empty-pool fallback succeeded: `ready-pool-empty-fallback-2.json` records Ready **106.719641 s**, First **114.613331 s**, Complete **115.904814 s**, Flow **116.834943 s**, and Greeting **0.930088 s**. This is the expected normal cold-provisioning fallback after the pool was empty.

`pool-refilled.json` at `17:27:56.199720+00:00` records two ready replacement bundles after the assignments. `pool-drained.json` at `17:30:44.490968+00:00` records three unused-bundle evictions, including the initial failed proof bundle, with zero `READY`, `PREPARING`, or `EVICTING` rows; its two assigned rows are byte-equal to the rows in `pool-two-assigned.json`. Unused credentials were revoked. The disabled-mode check records `enabled=False target=0` with no maintenance actions, and the three-step drain completed.

## Sources and retained artifacts

- `.tmp/alpha-benchmark-report.md` — baseline seven-run report.
- `.tmp/alpha-speed/measurements/` — candidate client measurements and Cloud/Foundry DB snapshots.
- `.tmp/alpha-speed/candidate-series.log`, `candidate-asleep-series.log`, `candidate-intent-series.log`, and `corrected-intent-series.log` — poll and intent traces.
- `.tmp/alpha-speed/candidate-resource-pressure.txt` and `.tmp/alpha-speed/slow-start-runtime.log` — resource and startup diagnostics.
- `.tmp/alpha-speed/bootstrap-helper-proof-3.json` and `.tmp/alpha-speed/bootstrap-helper-proof-3.log` — corrected helper proof.
- `.tmp/alpha-speed/measurements/alpha-benchmark-ready-pool-{a,b}.json`, `alpha-benchmark-ready-pool-empty-fallback-2.json`, `pool-two-ready.json`, `pool-two-assigned.json`, `pool-refilled.json`, and `pool-drained.json` — ready-pool assignment, fallback, refill, and drain proof.
- `.tmp/alpha-speed/pool-health-before-claim.log`, `pool-assignment-benchmarks.log`, `pool-disabled-noop.log`, and the pool drain/refill logs — pool maintenance and disabled-mode traces.

## Delivery validation and retained environment

The final backend suite passed 536 tests with 10 skips; runtime passed 397 with 5 skips and 90.13% coverage; the PostgreSQL pool recovery/concurrency suite passed 46; the final hint acknowledgement timestamp change passed 14 focused tests and independent review. The final backend integration revision is `658f6d9`; the immutable runtime image above contains `e9ead8a`.

The local pool target was restored to zero. All 11 retained test Machines across the six recorded test Apps were verified stopped; assigned workspaces and their data were retained. All unused pool Apps were verified absent. Raw diagnostic artifacts listed above are retained locally and are not committed in this repository.
