import secrets
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest, JsonResponse
from ninja_extra import NinjaExtraAPI
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from auths.exceptions import WorkspaceAccessDenied
from integrations.api.controllers import (
    CalendarController,
    GmailCallbackController,
    GmailController,
)
from integrations.api.safe_inputs import SafeInputController
from integrations.services.calendar_tool import execute_calendar_tool
from integrations.services.gmail_tool import execute_gmail_tool
from integrations.services.safe_inputs import (
    execute_browser_tool,
    execute_safe_input_tool,
)

_MAX_TOOL_BYTES = 64 * 1024
_TOOLS = {
    "gmail": execute_gmail_tool,
    "calendar": execute_calendar_tool,
    "safe_inputs": execute_safe_input_tool,
    "browser": execute_browser_tool,
}


def _foundry_token_valid(request: HttpRequest) -> bool:
    value = request.headers.get("Authorization", "")
    configured = str(getattr(settings, "ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN", ""))
    if not configured or not value.startswith("Bearer "):
        return False
    token = value[7:]
    return bool(token) and secrets.compare_digest(token.encode(), configured.encode())


class IntegrationToolEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: UUID | None = None
    run_id: UUID | None = None
    binding_id: UUID
    command_fingerprint: str
    call_id: UUID
    integration: str
    arguments: dict

    @model_validator(mode="after")
    def one_turn_identity(self):
        if (self.message_id is None) == (self.run_id is None):
            raise ValueError("exactly one tool turn identity is required")
        return self


def register(api: NinjaExtraAPI) -> None:
    api.register_controllers(
        GmailController,
        CalendarController,
        GmailCallbackController,
        SafeInputController,
    )

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
        handler = _TOOLS.get(payload.integration)
        if handler is None:
            return JsonResponse({"error": "integration_unsupported"}, status=422)
        fields = payload.model_dump(exclude={"integration"})
        try:
            status, result = handler(**fields)
        except (ObjectDoesNotExist, PermissionError, WorkspaceAccessDenied):
            return JsonResponse({"error": "integration_unavailable"}, status=403)
        return JsonResponse(result, status=status)
