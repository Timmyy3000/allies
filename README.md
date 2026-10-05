# Allies

**Personal AI helpers built around what matters to you — on your own server.**

Allies lets you create a small team of AI helpers ("allies"), each with its own
name, job and personality. They chat with you, remember context, run routines
on a schedule, ask before doing anything sensitive, and work with your Gmail
and Google Calendar. Every ally runs on [Hermes](https://github.com/NousResearch/hermes-agent)
inside an isolated, sandboxed runtime that you host.

Allies is self-hostable in the same spirit as Supabase or Cal.com: one Docker
Compose stack, signups closed by default, and your data stays on your machine.

> **Status:** early. Allies is moving from a hosted beta to an open-source,
> self-hosted product. Expect breaking changes before `1.0`.

## Features

- **Multiple allies**, each with its own personality, memory and skills.
- **Streaming chat** with live activity: see what your ally is doing as it works.
- **Approvals** for sensitive actions, with push notifications.
- **Routines**: scheduled work your allies run and report back on.
- **Integrations**: Gmail (read, search, attachments) and Google Calendar.
- **File uploads** with size and type validation; optional ClamAV malware scanning.
- **Bring your own model** via any OpenAI-compatible endpoint (OpenRouter by default).
- **Sandboxed runtimes**: each workspace runs Hermes in its own container pair with bubblewrap isolation.

## Architecture

```
Browser / PWA ──► Web (Next.js) ──► Cloud (Django) ──► Foundry (Django) ──► Workspace runtime
                                     users, chats,      executions, leases,    Hermes + allies-runtime
                                     routines, files    runtime lifecycle      (one container pair
                                                                                per workspace)
```

| Path | What it is |
| --- | --- |
| `apps/web` | Next.js web app (installable PWA) |
| `apps/mobile` | Expo mobile app (not yet supported for self-hosting) |
| `packages/` | Shared TypeScript packages: the Cloud API client and Ally motion |
| `services/cloud` | **Cloud** — product truth: accounts, allies, conversations, routines, files, integrations |
| `services/foundry` | **Foundry** — runtime truth: provisions workspace runtimes, runs and fences executions; `runtime/` holds the runtime and Hermes images |
| `deploy/` | Self-hosting: Docker Compose stack, Caddy router, environment template |

Cloud never talks to Hermes directly; Foundry owns every runtime. The runtime
connects outbound to Foundry, so workspace containers expose no ports.

## Self-hosting

### Requirements

- A Linux server with Docker and Docker Compose; 4 GB RAM minimum, 8 GB recommended.
- A domain name pointing at the server, and a TLS-terminating proxy (Caddy, Traefik, nginx…).
- An API key for an OpenAI-compatible model provider (e.g. OpenRouter), plus an
  OpenAI key for onboarding greetings.
- A Google OAuth client for sign-in and the Gmail and Calendar integrations.

### Quick start

```sh
git clone https://github.com/Timmyy3000/allies.git
cd allies/deploy
cp .env.example .env          # fill in your domain, secrets and keys
sudo mkdir -p /var/lib/allies/secrets && sudo chmod 700 /var/lib/allies/secrets
docker compose up -d --build
```

The stack serves HTTP on `127.0.0.1:8080`. Point your TLS proxy at it for your
domain. In your Google OAuth client, add these redirect URIs:

- `https://<your-domain>/api/v1/auths/callback/google`
- `https://<your-domain>/api/v1/integrations/gmail/callback`

Sign in with an email listed in `ALLIES_SIGNUP_ALLOWED_EMAILS`. Everyone else
needs an invite.

### Host notes

- **Ubuntu 24.04+** restricts user namespaces, which the Hermes sandbox needs.
  Load the bundled AppArmor profile and set `ALLIES_DOCKER_APPARMOR_PROFILE=allies-hermes`:
  ```sh
  sudo cp deploy/apparmor-allies-hermes /etc/apparmor.d/allies-hermes
  sudo apparmor_parser -r /etc/apparmor.d/allies-hermes
  ```
- **Memory.** Runtimes stay warm by default (about 400 MB per workspace). Set
  `ALLIES_RUNTIME_IDLE_STOP_ENABLED=true` to stop idle runtimes at the cost of a
  slower first reply.
- **Malware scanning** is off by default. To scan uploads, set
  `ALLIES_FILE_MALWARE_SCAN=true` and start with `docker compose --profile clamav up -d`
  (about 1 GB RAM).

### Updating

```sh
allies/deploy/update.sh stable    # or nightly
```

Migrations run automatically on startup.

## Releases and branches

| Branch | Purpose | Versions |
| --- | --- | --- |
| `nightly` | Default branch. All pull requests target it; it deploys to the reference instance for testing. | `nightly-0.1`, `nightly-0.2`, … |
| `stable` | Tested releases, promoted from `nightly`. Run this in production. | `v0.1.0`, `v0.2.0`, … |

## Development

Requirements: [Bun](https://bun.sh) 1.2, [uv](https://docs.astral.sh/uv/) with Python 3.13, and Docker.

```sh
bun install          # web, mobile and packages
bun run dev:web      # web app on http://localhost:3000
```

To run Cloud and Foundry locally, follow `services/cloud/README.md` and
`services/foundry/README.md`.

Checks, matching CI:

```sh
bun run lint && bun run typecheck && bun run test:run    # web and packages
cd services/cloud/backend && uv run pytest               # Cloud
cd services/foundry && make check                        # Foundry
```

See each service's `README.md` for more, and `ENGINEERING_STYLE.md` for conventions.

## Contributing

Open pull requests against `nightly`. Keep them small and focused, include
tests for behavior changes, and make sure CI passes. Read `AGENTS.md` and
`ENGINEERING_STYLE.md` before larger changes.

## License

Not yet chosen. Until a license is added, all rights are reserved.
