import secrets
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest, JsonResponse
from ninja_extra import NinjaExtraAPI
from pydantic import BaseModel, ConfigDict, ValidationError

from auths.exceptions import WorkspaceAccessDenied
from integrations.api.controllers import GmailCallbackController, GmailController
from integrations.services.gmail_tool import execute_gmail_tool

_MAX_TOOL_BYTES = 64 * 1024


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
    def integration_tool(request: HttpRequest):
        try:
            declared = int(request.headers.get("Content-Length") or 0)
        except ValueError:
            declared = 0
        if declared > _MAX_TOOL_BYTES or len(request.body) > _MAX_TOOL_BYTES:
            return JsonResponse({"error": "request_too_large"}, status=413)
        try:
            payload = IntegrationToolEnvelope.model_validate_json(request.body)
        except ValidationError:
            return JsonResponse({"error": "invalid_request"}, status=422)
        if payload.integration != "gmail":
            return JsonResponse({"error": "integration_unsupported"}, status=422)
        fields = payload.model_dump(exclude={"integration"})
        try:
            status, result = execute_gmail_tool(**fields)
        except (ObjectDoesNotExist, PermissionError, WorkspaceAccessDenied):
            return JsonResponse({"error": "integration_unavailable"}, status=403)
        return JsonResponse(result, status=status)
