# Allies Interface

The web and mobile clients for Allies.

## Applications

- `apps/web`: Next.js web application
- `apps/mobile`: Expo mobile application

## Development

Install all workspace dependencies from the repository root:

```bash
bun install
```

Run the web application:

```bash
bun run dev:web
```

Run the mobile application:

```bash
bun run dev:mobile
```

Copy `.env.example` to an ignored local environment file and set the public
Cloud origin for each app. Public configuration is validated at runtime and
must use HTTPS outside local development.

## Validation

Run the complete Interface foundation checks from the repository root:

```bash
bun run cloud:check
bun run typecheck
bun run test:run
bun run lint
bun run build:web
bun run bundle:mobile
```

`cloud:check` uses the committed Allies Cloud OpenAPI snapshot. Builds and
ordinary tests do not depend on staging availability.
