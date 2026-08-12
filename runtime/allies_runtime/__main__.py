"""Image-baked PID-1 entrypoint for ``allies-runtime``."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from .composition import RuntimeComposition, compose_runtime, run_worker
from .config import CredentialReference, SettingsError, load_settings
from .foundry import FoundryClient
from .hermes import (
    DEFAULT_CREDENTIAL_SOCKET,
    HermesClient,
    UnixSocketCredentialResolver,
    test_credential_for_reference,
)
from .smoke import run_smoke_sync

_HERMES_STARTUP_GRACE_SECONDS = 60.0
_MAX_RUNTIME_CREDENTIAL_BYTES = 4096
_SECRETS_ROOT = Path("/run/secrets")


def worker_entrypoint(
    *,
    settings: Any,
    foundry: FoundryClient,
    credential_resolver: Callable[..., Any],
    hermes: Any | None = None,
    api_key_factory: Callable[[], str] | None = None,
    max_turns: int | None = None,
    idle_cycles: int | None = 1,
    idle_delay: float = 0.0,
) -> int:
    """Run the production worker through the explicit composition boundary."""

    composition: RuntimeComposition = compose_runtime(
        settings,
        foundry,
        credential_resolver,
        hermes=hermes,
        api_key_factory=api_key_factory,
    )
    try:
        asyncio.run(
            run_worker(
                composition,
                max_turns=max_turns,
                idle_cycles=idle_cycles,
                idle_delay=idle_delay,
            )
        )
    except KeyboardInterrupt:
        return 0
    return 0


def file_credential_for_reference(reference: CredentialReference) -> str:
    """Read one bounded credential from a Fly-mounted secret file."""

    parsed = urlsplit(str(reference))
    if parsed.scheme != "file" or parsed.netloc or parsed.query or parsed.fragment:
        raise SettingsError("runtime credential must be a local file reference")
    path = Path(url2pathname(unquote(parsed.path)))
    if ".." in path.parts:
        raise SettingsError("runtime credential must remain under /run/secrets")
    secrets_root = _SECRETS_ROOT.resolve()
    try:
        path = path.resolve()
        path.relative_to(secrets_root)
    except (OSError, ValueError) as exc:
        raise SettingsError(
            "runtime credential must remain under /run/secrets"
        ) from exc
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SettingsError("runtime credential is unavailable") from exc
    if not raw or len(raw) > _MAX_RUNTIME_CREDENTIAL_BYTES:
        raise SettingsError("runtime credential has an invalid size")
    try:
        value = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise SettingsError("runtime credential must be UTF-8") from exc
    if not value or "\r" in value or "\n" in value:
        raise SettingsError("runtime credential is not a header value")
    return value


def _default_credential_resolver(
    reference: CredentialReference, values: dict[str, object]
) -> Callable[[CredentialReference], str]:
    if str(reference).lower().startswith("test://fnd004/"):
        return test_credential_for_reference
    if urlsplit(str(reference)).scheme.lower() == "file":
        return file_credential_for_reference
    return UnixSocketCredentialResolver(
        str(values.get("HERMES_CREDENTIAL_SOCKET", DEFAULT_CREDENTIAL_SOCKET))
    )


def runtime_entrypoint(
    *,
    env: dict[str, object] | None = None,
    credential_resolver: Callable[..., Any] | None = None,
    foundry_credential_resolver: Callable[[CredentialReference], str] | None = None,
    foundry_factory: Callable[..., FoundryClient] = FoundryClient,
    hermes: Any | None = None,
    idle_cycles: int | None = None,
) -> int:
    """Probe Hermes, compose the production worker, and poll until fenced."""

    values = dict(os.environ) if env is None else dict(env)
    if not values.get("HERMES_CREDENTIAL_REF"):
        return 1
    try:
        settings = load_settings(values)
        if credential_resolver is None:
            credential_resolver = _default_credential_resolver(
                settings.credential_ref, values
            )
        resolve_foundry = foundry_credential_resolver or file_credential_for_reference
        runtime_token = resolve_foundry(settings.foundry_credential_ref)
        foundry = foundry_factory(
            base_url=settings.foundry_origin,
            runtime_token=runtime_token,
        )
        readiness_client = hermes or HermesClient(settings, credential_resolver)
    except (OSError, SettingsError, TypeError, ValueError):
        return 1
    deadline = time.monotonic() + _HERMES_STARTUP_GRACE_SECONDS
    while not asyncio.run(probe_readiness(readiness_client)):
        if time.monotonic() >= deadline:
            return 1
        time.sleep(0.25)
    return worker_entrypoint(
        settings=settings,
        foundry=foundry,
        credential_resolver=credential_resolver,
        # A production worker must compose its own profile-aware Hermes client.
        # An explicitly injected client remains available for tests/integrations.
        hermes=hermes,
        idle_cycles=idle_cycles,
        idle_delay=0.25,
    )


async def probe_readiness(client: Any) -> bool:
    """Return ready only after an authenticated Hermes health request."""

    try:
        health = await client.health_detailed()
    except Exception:  # noqa: BLE001 - readiness must fail closed
        return False
    status = getattr(health, "status", None)
    if isinstance(status, str) and status.lower() in {"ok", "ready", "healthy"}:
        return True
    if not isinstance(status, str) or status.lower() != "degraded":
        return False
    readiness = getattr(health, "readiness", None)
    if not isinstance(readiness, dict):
        return False
    checks = readiness.get("checks")
    if not isinstance(checks, dict):
        return False
    gateway = checks.get("gateway")
    return (
        isinstance(gateway, dict)
        and gateway.get("status") == "ok"
        and gateway.get("state") == "running"
    )


def serve(
    *, client: Any | None = None, credential_resolver: Callable[..., Any] | None = None
) -> int:
    """Probe authenticated Hermes, then keep the image's PID 1 alive.

    The image process never resolves a plaintext credential itself.  An
    operator supplies a secure resolver at the composition boundary; without
    that resolver (or the opaque reference it needs) the process exits before
    claiming readiness.
    """

    if client is None:
        if not os.environ.get("HERMES_CREDENTIAL_REF"):
            return 1
        try:
            if credential_resolver is None:
                reference = CredentialReference(os.environ["HERMES_CREDENTIAL_REF"])
                credential_resolver = _default_credential_resolver(
                    reference, dict(os.environ)
                )
            settings = load_settings(dict(os.environ))
            client = HermesClient(settings, credential_resolver)
        except (SettingsError, ValueError, TypeError):
            return 1
    # The proof-only temporary-profile bootstrap runs after the Machine has
    # started. Keep PID 1 alive, but unready, during that bounded handoff so
    # the bootstrap can install the matching Hermes key/profile before the
    # authenticated probe succeeds. Production/socket references still fail
    # closed immediately when their resolver or key is unavailable.
    reference = os.environ.get("HERMES_CREDENTIAL_REF", "").lower()
    deadline = time.monotonic() + (
        _HERMES_STARTUP_GRACE_SECONDS if reference.startswith("test://fnd004/") else 0.0
    )
    try:
        while not asyncio.run(probe_readiness(client)):
            if time.monotonic() >= deadline:
                return 1
            time.sleep(0.25)
    except KeyboardInterrupt:
        return 0

    async def wait_for_shutdown() -> None:
        await asyncio.Event().wait()

    try:
        asyncio.run(wait_for_shutdown())
    except KeyboardInterrupt:
        return 0
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Allies runtime proof harness")
    parser.add_argument("--smoke", choices=("fake", "live"))
    parser.add_argument(
        "--serve",
        action="store_true",
        help="keep the runtime process alive as the container PID 1",
    )
    args = parser.parse_args()
    if args.serve and args.smoke:
        parser.error("--serve and --smoke cannot be combined")
    if args.serve:
        return serve()
    if args.smoke is None:
        return runtime_entrypoint()
    result = run_smoke_sync(args.smoke)
    print(json.dumps(result.to_dict(), sort_keys=True))
    return (
        0 if all(item["status"] != "fail" for item in result.to_dict()["checks"]) else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
