---
title: Allies Backend Development Guide
status: working draft
audience: Allies Cloud and Allies Foundry engineers and agents
canonical_nabu: projects/allies/engineering/guides/backend-development.md
---

# Allies Backend Development Guide

## Status and purpose

This is a working engineering convention for the Allies Cloud and Allies Foundry Django backends.

It is intentionally not a finalized product architecture. The domain list, model details, routes, and integration contracts will be refined as each backend is built. Sections marked **Proposed** describe defaults to use unless a domain has a concrete reason to differ.

The guide is for:

- engineers joining either backend;
- agents implementing or reviewing backend work;
- contributors deciding where a new piece of code belongs.

When this guide and the code disagree, the code and its tests describe the current implementation. If the difference is intentional, record the decision and update this guide when the convention is accepted.

## Current repository baseline

Both repositories use:

- Python 3.13;
- Django 6.0;
- Django Ninja Extra for the API;
- uv for Python dependency and command management;
- one framework-native Django project named `config`;
- one codebase that can run as web, worker, scheduler, and migration processes.

The Django project lives under `backend/`. Run Django and uv commands from that directory unless a root Make target delegates there.

The repositories have different ownership boundaries:

- **Cloud** owns customer-facing product truth, including users, tenants, Allies, conversations, responsibilities, approvals, credentials, billing, and the visible view of work.
- **Foundry** owns durable runtime and execution truth, including runtime profiles, workspaces, executions, attempts, leases, events, provider bindings, and runtime adapters.

Cloud and Foundry do not share Django models, databases, migrations, or queues. Cloud speaks to Foundry through a versioned API. Vendor concepts should not leak through every domain module.

## First principles

### Start from a domain boundary

A Django app represents a meaningful business or runtime domain. It should not be created only because a table, endpoint, or helper function exists.

Before creating an app, write down:

- what the domain owns;
- what it does not own;
- the state it persists;
- the use cases it supports;
- the systems it is allowed to call.

App names and the final domain list remain proposed until the domain work makes them concrete.

### Start compact, but give real capabilities a home

Create an app when its first feature begins. Do not generate empty scaffolding for every possible future domain.

Within an app, create `services/` and `api/controllers/` as folders from the first commit. This keeps write workflows and route families easy to split as they grow.

Other layers are added when they earn their place. In particular, a query package is optional.

### Prefer explicit boundaries

Use clear service, query, access, and gateway functions over a generic repository abstraction or hidden discovery mechanism.

The code should make it possible to answer:

- which use case is running;
- which transaction owns it;
- which tenant is in scope;
- which permission was checked;
- which external system was called;
- what can be retried.

## Standard app shape (Proposed)

A new domain app should begin close to this shape:

```text
domain/
├── __init__.py
├── apps.py
├── admin.py
├── models.py
├── api/
│   ├── __init__.py
│   ├── register.py
│   ├── schemas.py
│   └── controllers/
│       ├── __init__.py
│       └── collection.py
├── services/
│   ├── __init__.py
│   └── create_domain_object.py
├── migrations/
│   └── __init__.py
└── tests/
    ├── __init__.py
    ├── test_models.py
    ├── test_services.py
    └── test_api.py
```

Add these only when needed:

```text
domain/
├── access.py or access/
├── exceptions.py
├── queries/                 # only when read logic earns a boundary
├── tasks.py
├── gateways/
├── events.py
└── handlers.py
```

If `models.py`, `schemas.py`, or another module becomes difficult to navigate, split it by capability. Do not split files simply to satisfy a fixed line count.

## Layer responsibilities

The following names have specific meanings in Allies code.

### Models

Models are the durable nouns and database invariants.

Models may contain:

- fields and relationships;
- indexes and database constraints;
- choices closely tied to the model;
- small methods describing the model's own state;
- custom querysets when they express a universal filtering rule.

Models should not contain:

- multi-model workflows;
- HTTP responses;
- Celery dispatch;
- Foundry, Fly, Hermes, Stripe, or email calls;
- request-specific authorization;
- large lifecycle procedures.

### Controllers

Controllers are HTTP adapters.

A controller should:

1. authenticate the request;
2. resolve the actor and tenant context;
3. validate the request schema;
4. call a service or read function;
5. translate the result into a response schema and HTTP status.

Controllers should not:

- coordinate several model writes;
- open their own transaction for a business workflow;
- call external systems directly;
- contain a large conditional workflow;
- return domain-specific HTTP errors from deep service code.

### Schemas

Schemas define API input and output contracts.

Use operation-specific names such as:

```python
AllyCreateRequest
AllyUpdateRequest
AllyDetail
AllyListItem
```

Do not use one schema for creation, update, list, and detail responses just because the fields overlap.

Schemas validate and serialize data. They should not query the database or mutate state.

### Services

Services are application use cases. They are usually verbs.

Examples:

```text
create_ally
update_ally_identity
archive_ally
send_message
accept_responsibility
```

A service should:

- accept explicit inputs;
- enforce the relevant access and domain rules;
- own the transaction boundary for its write;
- coordinate models within its domain;
- call another domain through a public service or gateway boundary;
- enqueue asynchronous work with `transaction.on_commit()` when appropriate;
- return a domain object or a typed result.

Prefer functions for simple use cases. Use a class when dependencies or state make it clearer.

Services should not return HTTP responses. Raise named domain exceptions and translate them at the API boundary.

### Access and policies

Access code answers permission and authorization questions.

Central tenancy authorization should define roles, memberships, and generic tenant-level capabilities. A domain may define resource-specific access rules in `access.py` or an `access/` package.

For example:

- tenancy authorization: can this actor edit anything in this tenant?
- Ally access: can this actor edit this Ally?
- service: perform the edit.

Do not create one global resource switchboard that imports every domain model and resolves resources by string type. That pattern combines authentication, resource lookup, authorization, and HTTP behavior into one growing module.

### Queries

A query is a read-only data access function. A `queries/` package is optional.

Simple read use cases may use Django ORM directly from a read-oriented service module. Extract a query boundary when the read is:

- reused by multiple callers;
- tenant or permission scoped in a non-trivial way;
- expensive or performance-sensitive;
- a product-specific projection;
- difficult to test without a named query.

Queries must not save models, dispatch tasks, call external systems, or mutate state.

Do not add a generic repository layer over Django ORM without a concrete need.

### Tasks

Tasks are asynchronous entry points, not alternate business implementations.

A task should:

- accept stable identifiers and serializable inputs;
- call a service;
- be safe to retry;
- make idempotency explicit;
- record or surface failure clearly.

Keep transaction and business logic in services. Dispatch after the database commit when a task depends on newly persisted state.

### Gateways and adapters

Gateways translate between an Allies domain and an external system.

Examples include:

- the Cloud Foundry gateway;
- Foundry Fly provider adapters;
- Foundry Hermes runtime adapters;
- email, object storage, or billing clients.

Keep vendor-specific request and response shapes inside the gateway. Domain services should receive domain-shaped results and errors.

### Events and handlers

Use explicit events or handlers for cross-domain reactions when direct synchronous coupling would make ownership unclear.

Do not use signals for normal product workflows. Signals may register framework hooks, but they must not hide important business behavior or make external calls during app initialization.

## Splitting controllers

Controllers should be split by resource or capability, not by HTTP verb alone.

A growing app may look like:

```text
api/controllers/
├── collection.py       # list and create
├── detail.py           # retrieve and update
├── lifecycle.py        # archive, restore, activate
└── responsibilities.py # responsibility-specific routes
```

Split a controller when:

- it handles unrelated resources;
- it contains unrelated route prefixes;
- it needs several workflow helpers;
- it starts coordinating model writes or external calls;
- its responsibility cannot be described in one sentence.

A controller can be small without being artificially limited to one endpoint.

## Splitting services

Services should be split by business capability and transaction boundary.

Start with one module per real use case or closely related capability:

```text
services/
├── create_ally.py
├── update_ally.py
├── archive_ally.py
└── provision_profile.py
```

A service module needs splitting when:

- it contains unrelated use cases;
- its functions have different dependencies or transaction boundaries;
- it needs flags such as `mode`, `force`, or `sync` to change its meaning;
- its tests require unrelated fixtures;
- it coordinates several external systems;
- its name becomes generic, such as `DomainService` or `Manager`.

Do not create a single service class that accumulates every action in a domain.

## API registration

The current bootstrap includes `backend/config/api.py` with the root
`NinjaExtraAPI`, and `config/urls.py` mounts it at `/api/v1/`. Add each domain
registrar to that root explicitly as the domain is introduced.

The registration path should be explicit:

```text
domain/api/controllers/*.py
        ↓
domain/api/register.py
        ↓
config/api.py
        ↓
config/urls.py
        ↓
/api/v1/...
```

The app-level registrar owns the list of controllers for that app:

```python
# domain/api/register.py
from ninja_extra import NinjaExtraAPI

from .controllers.collection import DomainCollectionController


def register(api: NinjaExtraAPI) -> None:
    api.register_controllers(DomainCollectionController)
```

The root API composes app registrars:

```python
# config/api.py
from domain.api.register import register as register_domain_api

api = NinjaExtraAPI(
    title="Allies API",
    version="0.1.0",
)


def register_all_apis() -> None:
    register_domain_api(api)


register_all_apis()
```

The URL configuration mounts the API once:

```python
# config/urls.py
path("api/v1/", api.urls)
```

Do not use automatic controller discovery. Explicit registration makes API composition, imports, and review predictable.

## Authorization and tenant scope

Every request that reaches tenant-owned data must resolve a tenant explicitly.

For each use case, identify:

- actor;
- tenant;
- resource;
- required capability or role;
- ownership and lifecycle checks.

Controllers may resolve authentication and basic tenant context. Services must still enforce the relevant access rule because services can also be called by tasks, admin flows, or other internal code.

Tenant filtering should be visible in queries and services. Do not rely on callers to remember an implicit filter.

## Cross-app dependencies

Allowed dependencies should point toward domain contracts, not internal implementation details.

Prefer:

```text
controller
  → service or read function
  → domain model / gateway
```

For cross-domain work:

```text
Cloud product domain
  → foundry_gateway
  → versioned Foundry API
```

Avoid:

- controllers importing foreign-domain models to reproduce workflows;
- circular imports hidden behind dynamic model lookups;
- sharing Django models between Cloud and Foundry;
- leaking Fly, Hermes, or provider concepts into Cloud product models;
- making a common package a dumping ground for unproven helpers.

## Transactions, external calls, and retries

A service owns the transaction for a write workflow.

Within a transaction:

- validate state transitions;
- persist product or runtime state;
- record idempotency keys or durable intent when required.

After commit:

- dispatch Celery work;
- call external systems when the design requires asynchronous execution;
- publish events that depend on committed state.

External operations must define:

- idempotency behavior;
- retryability;
- timeout behavior;
- failure state;
- compensation or reconciliation behavior.

Do not hold a database transaction open while waiting on a remote service unless a documented invariant requires it.

## Models and migrations

Use Django migrations generated by Django:

POSIX shells:

```sh
export DJANGO_DEBUG=true
cd backend
uv run python manage.py makemigrations <app>
uv run python manage.py migrate
```

PowerShell:

```powershell
$env:DJANGO_DEBUG = "true"
cd backend
uv run python manage.py makemigrations <app>
uv run python manage.py migrate
```

Do not hand-write migration files.

Use database constraints for invariants that must hold regardless of caller. Use service validation for workflows and state transitions.

When changing models:

1. update the model;
2. generate the migration;
3. inspect the migration;
4. run targeted model and service tests;
5. run Django checks and migration checks.

## Testing boundaries

Every domain should test the boundaries it owns.

Minimum expectations for a feature:

- model tests for constraints and state behavior;
- service tests for use cases and transactions;
- API tests for authentication, schemas, status codes, and response shape;
- gateway or contract tests for external boundaries;
- task tests for retry and idempotency behavior when tasks exist.

Prefer targeted tests while building, then run the repository suite before handoff.

Tests should prove tenant isolation and failure behavior, not only the successful path.

## Local development commands

Production-safe settings are the default. For local development, export the
explicit debug flag before running Django commands so the SQLite fallback is
available:

POSIX shells:

```sh
export DJANGO_DEBUG=true
make sync
make check
make migrate
make server
```

PowerShell:

```powershell
$env:DJANGO_DEBUG = "true"
make sync
make check
make migrate
make server
```

Deployments must set `DJANGO_DEBUG=false`, `DJANGO_SECRET_KEY`, and
`DATABASE_URL` through the platform's secret/environment configuration. Set
`DJANGO_ALLOWED_HOSTS` and opt into trusted proxy headers only when a
TLS-terminating proxy strips and rewrites `X-Forwarded-Proto`:

```text
DJANGO_TRUST_PROXY_HEADERS=true
DJANGO_TRUSTED_PROXY_IPS=192.0.2.10/32,2001:db8:1234::/48
```

`DJANGO_TRUSTED_PROXY_IPS` is a comma-separated list of the proxy's IPv4/IPv6
addresses or CIDR networks. Foundry removes `X-Forwarded-Proto` before Django's
security middleware when the connection does not come from one of those
networks, so a direct app connection cannot spoof HTTPS. Enabling
`DJANGO_TRUST_PROXY_HEADERS` without an explicit allowlist fails configuration
validation. In trusted-proxy mode, the backend redirects HTTP requests to HTTPS
and enables one-year HSTS; leave both settings off for direct/local deployments.

## Health endpoint

`GET /healthz` is the public liveness/readiness contract. It requires
no authentication and returns `{"status": "ok"}` with HTTP 200 after a
successful database probe, or `{"status": "unavailable"}` with HTTP 503 when
the database probe fails or is still unavailable. PostgreSQL's first request
per worker performs one bounded five-second probe before replying; later
refreshes run in a single background worker. Results are cached for one second,
and callers receive the last result while a refresh is in flight. The endpoint
does not accept request data and should be used only for platform health
checks, not application traffic.

The repository root provides the current convenience commands. Set
`DJANGO_DEBUG=true` in your shell first, as shown above:

```powershell
make sync
make check
make validate
make migrate
make server
```

For a one-shot POSIX invocation, use:

```sh
DJANGO_DEBUG=true make sync
DJANGO_DEBUG=true make check
DJANGO_DEBUG=true make validate
DJANGO_DEBUG=true make migrate
DJANGO_DEBUG=true make server
```

Other current targets include:

```text
make app NAME=<domain>
make test
make migrate
make migrations APP=<domain>
make format
make lint
make shell
```

`make app NAME=<domain>` invokes the `startdomain` management command. It
generates the agreed Allies app shape, but it does not silently modify
`INSTALLED_APPS` or top-level API registration. Those changes remain explicit
so they are visible in review.

`make check` runs the quick Django configuration and missing-migration checks.
`make validate` runs the full repository validation command, including the
lockfile check and tests. CI uses the same Python validation runner.

The runtime cleanup expiry entrypoint does not require a third-party scheduler.
Run one bounded pass with:

POSIX shell:

```sh
export DJANGO_DEBUG=true
cd backend
uv run --locked python manage.py expire_profile_cleanups
```

PowerShell:

```powershell
$env:DJANGO_DEBUG = "true"
cd backend
uv run --locked python manage.py expire_profile_cleanups
```

For a supervised periodic process, use the bounded watch mode and let the
deployment process restart it after the requested number of passes:

POSIX shell:

```sh
export DJANGO_DEBUG=true
cd backend
uv run --locked python manage.py expire_profile_cleanups --watch --interval 60 --max-runs 60
```

PowerShell:

```powershell
$env:DJANGO_DEBUG = "true"
cd backend
uv run --locked python manage.py expire_profile_cleanups --watch --interval 60 --max-runs 60
```

The example performs at most 60 passes, one minute apart, and then exits.
`--watch` requires `--max-runs`; supported bounds are 1-3600 seconds for
`--interval` and 1-1440 passes for `--max-runs`. The one-shot command remains
the default and is idempotent, so cron or a platform job may invoke it
directly when a periodic process is not needed.

## Definition of done for a new domain slice

Before calling a domain slice ready for review, confirm:

- ownership and non-ownership are written down;
- the app boundary is justified;
- models have constraints and migrations;
- controllers are split by route family;
- writes use focused services;
- access rules are explicit;
- read logic is appropriately simple or has a named query boundary;
- external calls are behind gateways;
- tasks are retry-safe;
- API registration is explicit;
- tests cover isolation and failure;
- the domain document and repository guide match the implementation.

## Open conventions

These remain intentionally open until implementation gives us evidence:

- the exact tenant role and capability model;
- whether the API uses an envelope or resource-first responses;
- whether `startdomain` should gain an explicit registration option;
- which worker and scheduler targets should be added with background processing;
- event and outbox conventions;
- standard pagination and filtering contracts;
- repository-specific observability conventions.

Related canonical notes:

- Allies codebase structure
- Allies engineering decision log
- Cloud and Foundry architecture specifications
- Conversation and streaming specification
- Foundry continuity layer specification
