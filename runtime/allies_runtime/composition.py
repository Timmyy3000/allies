"""Production composition for the Foundry-backed tenant worker."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .config import CredentialReference, RuntimeSettings
from .foundry import (
    DEFAULT_PROFILE_RECONCILE_INTERVAL,
    FoundryClient,
    FoundryWorker,
)
from .hermes import CredentialResolver, HermesClient
from .profile_store import ProfileStore
from .reconciliation import ProfileReconciler


@dataclass(frozen=True, slots=True)
class RuntimeComposition:
    """The fully wired runtime graph used by the production worker."""

    settings: RuntimeSettings
    foundry: FoundryClient
    hermes: Any
    profile_store: ProfileStore
    profile_reconciler: ProfileReconciler
    worker: FoundryWorker


def compose_runtime(
    settings: RuntimeSettings,
    foundry: FoundryClient,
    credential_resolver: CredentialResolver,
    *,
    hermes: Any | None = None,
    api_key_factory: Callable[[], str] | None = None,
    profile_reconcile_interval: float = DEFAULT_PROFILE_RECONCILE_INTERVAL,
) -> RuntimeComposition:
    """Build the production worker graph from validated runtime seams.

    Foundry owns its authenticated client at the process composition boundary.
    The same opaque-reference resolver is used for Hermes and for profile-local
    provider credentials; resolved values stay outside ``RuntimeSettings`` and
    the durable profile metadata.
    """

    if not isinstance(settings, RuntimeSettings):
        raise TypeError("runtime settings must be validated RuntimeSettings")
    if not callable(credential_resolver):
        raise TypeError("credential resolver must be callable")

    def resolve_profile_credential(reference: str) -> str:
        return credential_resolver(CredentialReference(reference))

    profile_store = ProfileStore(
        settings.volume_root,
        api_key_factory=api_key_factory,
        credential_resolver=resolve_profile_credential,
    )
    hermes_client = (
        hermes
        if hermes is not None
        else HermesClient(
            settings,
            credential_resolver,
            profile_credential_resolver=profile_store.read_api_key,
        )
    )
    profile_reconciler = ProfileReconciler(foundry, profile_store)
    worker = FoundryWorker(
        foundry,
        hermes_client,
        slots=settings.proof_slots,
        profile_reconciler=profile_reconciler,
        profile_reconcile_interval=profile_reconcile_interval,
    )
    return RuntimeComposition(
        settings=settings,
        foundry=foundry,
        hermes=hermes_client,
        profile_store=profile_store,
        profile_reconciler=profile_reconciler,
        worker=worker,
    )


def build_runtime(*args: Any, **kwargs: Any) -> RuntimeComposition:
    """Compatibility spelling for the explicit runtime composition factory."""

    return compose_runtime(*args, **kwargs)


def build_worker(*args: Any, **kwargs: Any) -> FoundryWorker:
    """Build only the worker while retaining the complete composition seam."""

    return compose_runtime(*args, **kwargs).worker


async def run_worker(
    composition: RuntimeComposition,
    *,
    max_turns: int | None = None,
    idle_cycles: int | None = 1,
    idle_delay: float = 0.0,
) -> tuple[Any, ...]:
    """Run the explicitly composed worker entrypoint."""

    return await composition.worker.run(
        max_turns=max_turns,
        idle_cycles=idle_cycles,
        idle_delay=idle_delay,
    )


__all__ = [
    "RuntimeComposition",
    "build_runtime",
    "build_worker",
    "compose_runtime",
    "run_worker",
]
