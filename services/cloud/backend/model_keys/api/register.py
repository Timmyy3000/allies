import logging
import secrets

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from ninja_extra import NinjaExtraAPI

from model_keys.api.controllers import ModelKeysController
from model_keys.api.schemas import CredentialResolveRequest
from model_keys.services import ModelKeyUnavailable, resolve_for_broker

logger = logging.getLogger(__name__)


def _broker_token_valid(request: HttpRequest) -> bool:
    value = request.headers.get("Authorization", "")
    configured = str(getattr(settings, "ALLIES_CREDENTIAL_BROKER_TOKEN", "") or "")
    if len(configured) < 32 or not value.startswith("Bearer "):
        return False
    return secrets.compare_digest(value[7:].encode(), configured.encode())


def register(api: NinjaExtraAPI) -> None:
    @api.post("/internal/credentials/resolve", auth=_broker_token_valid)
    def resolve_credential(request: HttpRequest, payload: CredentialResolveRequest):
        try:
            value = resolve_for_broker(
                workspace_id=payload.workspace_id, reference=payload.reference
            )
        except ModelKeyUnavailable:
            logger.info("credential broker refused", extra={"outcome": "refused"})
            response = JsonResponse({"code": "credential_unavailable"}, status=404)
        else:
            logger.info("credential broker resolved", extra={"outcome": "resolved"})
            response = JsonResponse({"value": value}, status=200)
        response["Cache-Control"] = "no-store"
        return response

    api.register_controllers(ModelKeysController)
