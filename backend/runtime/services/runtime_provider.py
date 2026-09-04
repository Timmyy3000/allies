from __future__ import annotations

import os

from django.conf import settings

from runtime.providers import FlyProvider


def runtime_power_provider() -> FlyProvider:
    """Build the maintenance provider from the one persisted-power secret."""

    proof_origin = getattr(settings, "ALLIES_FLY_API_BASE_URL", None)
    return FlyProvider(
        api_token=os.environ.get("FLY_API_TOKEN"),
        base_url=f"{proof_origin.rstrip('/')}/v1" if proof_origin else None,
        multi_container_enabled=True,
        file_secrets_enabled=True,
    )


__all__ = ["runtime_power_provider"]
