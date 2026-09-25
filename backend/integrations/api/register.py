import secrets
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest, JsonResponse
from ninja_extra import NinjaExtraAPI
from pydantic import BaseModel, ConfigDict

from auths.exceptions import WorkspaceAccessDenied
from integrations.api.controllers import GmailCallbackController, GmailController
from integrations.services.gmail_tool import execute_gmail_tool


def _foundry_token_valid(request: HttpRequest) -> bool:
    value = request.headers.get("Authorization", "")
    configured = str(getattr(settings, "ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN", ""))
    if not configured or not value.startswith("Bearer "):
        return False
    token = value[7:]
    return bool(token) and secrets.compare_digest(token.encode(), configured.encode())


class IntegrationToolEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: UUID
    binding_id: UUID
    command_fingerprint: str
    call_id: UUID
    integration: str
    arguments: dict


def register(api: NinjaExtraAPI) -> None:
    api.register_controllers(GmailController, GmailCallbackController)

    @api.post("/internal/foundry/integrations/tool", auth=_foundry_token_valid)
    def integration_tool(request: HttpRequest, payload: IntegrationToolEnvelope):
        if len(request.body) > 64 * 1024:
            return JsonResponse({"error": "request_too_large"}, status=413)
        if payload.integration != "gmail":
            return JsonResponse({"error": "integration_unsupported"}, status=422)
        fields = payload.model_dump(exclude={"integration"})
        try:
            status, result = execute_gmail_tool(**fields)
        except (ObjectDoesNotExist, PermissionError, WorkspaceAccessDenied):
            return JsonResponse({"error": "integration_unavailable"}, status=403)
        return JsonResponse(result, status=status)
