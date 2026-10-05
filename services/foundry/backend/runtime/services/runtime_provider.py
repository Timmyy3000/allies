from __future__ import annotations

import os

from django.conf import settings

from runtime.providers import FlyProvider


def runtime_provider_kind() -> str:
    """``fly`` (hosted) or ``docker`` (self-hosted, one machine per container pair)."""

    return os.environ.get("ALLIES_RUNTIME_PROVIDER", "fly").strip().lower() or "fly"


def runtime_power_provider():
    """Build the configured provider; Fly uses the one persisted-power secret."""

    if runtime_provider_kind() == "docker":
        from runtime.providers.docker import DockerProvider

        return DockerProvider.from_environment()
    proof_origin = getattr(settings, "ALLIES_FLY_API_BASE_URL", None)
    return FlyProvider(
        api_token=os.environ.get("FLY_API_TOKEN"),
        base_url=f"{proof_origin.rstrip('/')}/v1" if proof_origin else None,
        multi_container_enabled=True,
        file_secrets_enabled=True,
    )


__all__ = ["runtime_power_provider", "runtime_provider_kind"]
