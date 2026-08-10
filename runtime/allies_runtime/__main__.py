"""Image-baked PID-1 entrypoint for ``allies-runtime``."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections.abc import Callable
from typing import Any

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

_TEST_BOOTSTRAP_GRACE_SECONDS = 60.0


def worker_entrypoint(
    *,
    settings: Any,
    foundry: FoundryClient,
    credential_resolver: Callable[..., Any],
    hermes: Any | None = None,
    api_key_factory: Callable[[], str] | None = None,
    max_turns: int | None = None,
    idle_cycles: int = 1,
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


async def probe_readiness(client: Any) -> bool:
    """Return ready only after an authenticated Hermes health request."""

    try:
        health = await client.health_detailed()
    except Exception:  # noqa: BLE001 - readiness must fail closed
        return False
    status = getattr(health, "status", None)
    return isinstance(status, str) and status.lower() in {"ok", "ready", "healthy"}


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
                if str(reference).lower().startswith("test://fnd004/"):
                    credential_resolver = test_credential_for_reference
                else:
                    credential_resolver = UnixSocketCredentialResolver(
                        os.environ.get(
                            "HERMES_CREDENTIAL_SOCKET", DEFAULT_CREDENTIAL_SOCKET
                        )
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
        _TEST_BOOTSTRAP_GRACE_SECONDS if reference.startswith("test://fnd004/") else 0.0
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
    if args.serve or args.smoke is None:
        return serve()
    result = run_smoke_sync(args.smoke)
    print(json.dumps(result.to_dict(), sort_keys=True))
    return (
        0 if all(item["status"] != "fail" for item in result.to_dict()["checks"]) else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
