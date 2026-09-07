# Readiness defaults

Fast route; Markdown only. One independent PR into dev. User approved sensible defaults and a separate Railway readiness publisher. Railway owns autodeployment; no additional GitHub deployment workflow or IaC tooling.

Default Foundry/runtime activity waiting on, retain bounded waits (5 seconds/8 waiters), and use 16 web threads. Enable readiness hints when the existing Cloud URL/token are present, preserving explicit rollback overrides and validation. Pool target zero and idle stopping remain unchanged. The publisher already defaults to a one-second watch cadence.

Configure one staging publisher service from the same repository/Dockerfile, with the readiness publisher watch command as its start command and references to existing database/Cloud credentials. Railway handles subsequent staging deployments and restarts. No per-release operator command.

Validation: backend558passed/10skipped; runtime411passed/5skipped; dedicated publisher recovery/default cadence test passed. Ruff and web entrypoint default/override smoke passed. Independent simplicity/correctness review clean after aligning RuntimeSettings direct-construction default. Rollback uses explicit flags. Existing Fly image/config reconciliation remains separate; no latency guarantee.
