# Allies

Personal AI allies you can run on your own server.

## Layout

| Path | What it is |
| --- | --- |
| `apps/web` | Next.js web app |
| `apps/mobile` | Expo mobile app |
| `packages/` | Shared TypeScript packages (Cloud API client, Ally motion) |
| `services/cloud` | Cloud: accounts, conversations, and the public API (Django) |
| `services/foundry` | Foundry: provisions and drives Hermes runtimes (Django), plus the runtime and Hermes images in `runtime/` |
| `deploy/` | Self-hosting: Docker Compose and environment template |

Each service keeps its own `README.md` and `AGENTS.md`.

## Development

```sh
bun install          # web, mobile, packages
bun run dev:web
```

See `services/cloud/README.md` and `services/foundry/README.md` for the Python services.
