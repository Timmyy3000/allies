# Allies roadmap

Allies is an open-source, self-hostable product: one codebase that anyone can
run on their own server, with signups closed by default. This roadmap is
organized by release. Each release ships to `nightly` first (`nightly-X.Y`),
then to `stable` (`vX.Y.0`) once it has been tested on the reference instance.

Status: **Shipped**, **Next** (current release), **Planned**, **Later** (not yet scheduled).

## v0.1 — Self-hosted foundation (Shipped)

The hosted beta, moved onto a single server.

- Multiple Allies with name, avatar, job and personality; streaming chat with live activity.
- Approvals for sensitive actions; web push notifications.
- Routines: scheduled work that reports back.
- Gmail and Google Calendar integrations; per-Ally model selection.
- File uploads with size and type validation; optional ClamAV scanning.
- Docker Compose stack; Docker workspace provider (Hermes + allies-runtime per workspace).
- Invite-only signups with an owner email allowlist; Google sign-in.
- Monorepo with path-filtered CI; `nightly` / `stable` release branches.

## v0.2 — Easy to install and operate (Next)

Make a fresh install take minutes, and keep it healthy without reading code.

- **Published images.** Build and publish Cloud, Foundry, web, runtime and Hermes images to GHCR on every `nightly` and `stable` tag, so installs pull instead of build.
- **Installer.** One command that checks the host (Docker, RAM, AppArmor), generates secrets and writes `.env`.
- **First-run admin.** Create the owner account and manage invites from the app instead of the database.
- **Model setup without OpenAI lock-in.** Move onboarding greetings off the waitlist's OpenAI-only generator, then remove the waitlist entirely.
- **Upgrades and backups.** Documented upgrade path between releases; database and workspace-volume backup and restore.
- **Fewer moving parts.** Evaluate merging Cloud's worker and beat processes and trimming idle memory.
- **Open-source readiness.** Choose a license, audit history for secrets, add CONTRIBUTING and SECURITY policies.

## v0.3 — Finish the core experience (Planned)

Close the gaps left from the beta.

- **Stop a running reply.** Cancel an in-flight execution from the chat (Cloud stop lifecycle, Foundry cancellation, web control).
- **Reliable wake.** Requeue executions stranded by a failed wake instead of waiting for the next message.
- **Faster cold start.** Cut the ~45 s wake for instances that stop idle runtimes.
- **Ally and global settings.** Finish the remaining settings surfaces.
- **Push fallbacks.** Email for approvals and routine results when browser push is unavailable.

## v0.4 — Trust and operations (Planned)

Use Allies repeatedly and recover from failures without inspecting containers.

- Truthful failure and recovery states for wake, messages, routines and approvals.
- Ally deletion, usage limits and resource controls per workspace.
- An admin health page: runtimes, queues, storage, recent errors.
- Optional observability export (OpenTelemetry) instead of hosted sinks.
- Isolation proof between workspaces and Allies on a shared host.

## Later

- **Mobile app** with a configurable server URL.
- **Multi-user instances**: households and small teams sharing one server.
- **Memory consolidation** during idle periods.
- **More integrations** beyond Google.
- **Other runtime hosts**: keep the Fly provider working; consider Kubernetes.

## How this roadmap is maintained

Planned work becomes GitHub issues against `nightly`. Product and engineering
decisions are recorded in the project knowledge base and summarized here when a
release's scope changes.
