import secrets

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from ninja_extra import NinjaExtraAPI

from allies.api.controllers import (
    AllyController,
    OnboardingController,
    RuntimeIntentController,
)
from allies.gateways.foundry import ProfileReadinessHint
from allies.services.provisioning import accept_profile_readiness_hint


def _foundry_token_valid(request: HttpRequest) -> bool:
    value = request.headers.get("Authorization", "")
    configured = str(getattr(settings, "ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN", ""))
    if not configured or not value.startswith("Bearer "):
        return False
    token = value[7:]
    return bool(token) and secrets.compare_digest(token.encode(), configured.encode())


def register(api: NinjaExtraAPI) -> None:
    @api.post(
        "/internal/foundry/profile-readiness-hints",
        auth=_foundry_token_valid,
    )
    def profile_readiness_hint(request: HttpRequest, payload: ProfileReadinessHint):
        try:
            accept_profile_readiness_hint(payload)
        except ValueError:
            return JsonResponse({"status": "unavailable"}, status=404)
        return JsonResponse({"status": "accepted"}, status=202)

    api.register_controllers(
        OnboardingController, AllyController, RuntimeIntentController
    )
