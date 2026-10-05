from django.http import HttpRequest
from ninja_extra import ControllerBase, api_controller, http_delete, http_get, http_put

from allies.api.controllers import _has_browser_signal
from auths.api.common import (
    _require_origin,
    _session,
    error_json,
    error_responses,
    success_json,
)
from auths.api.schemas import SuccessResponse
from auths.config import native_enabled
from auths.exceptions import SessionInvalid, WorkspaceAccessDenied
from auths.models import SessionClientKind
from common.uuids import CanonicalUUID
from common.vault import VaultUnavailable
from model_keys.api.schemas import (
    ConnectKeyRequest,
    ModelKeysResponse,
    SelectModelRequest,
)
from model_keys.models import PROVIDERS, AllyModelSelection, ModelKey
from model_keys.services import (
    ModelKeyInvalid,
    ModelKeyMissing,
    ModelKeyUnavailable,
    connect_key,
    disconnect_key,
    get_state,
    select_model,
)


def _authenticate(request: HttpRequest):
    native = bool(request.headers.get("Authorization")) and not _has_browser_signal(
        request
    )
    if native and not native_enabled():
        raise SessionInvalid("session invalid")
    return _session(
        request,
        expected_client_kind=(
            SessionClientKind.NATIVE if native else SessionClientKind.BROWSER
        ),
    )


def _key_item(key: ModelKey) -> dict:
    return {
        "provider": key.provider,
        "key_hint": key.key_hint,
        "connected_at": key.connected_at.isoformat(),
    }


def _ally_item(selection: AllyModelSelection) -> dict:
    key = selection.model_key
    return {
        "ally_id": str(selection.ally_id),
        "source": "own_key" if key is not None else "org_default",
        "provider": key.provider if key is not None else None,
        "model": selection.model or None,
        "reasoning": selection.reasoning or None,
        "status": selection.status,
    }


def _state_json(user, workspace_id) -> dict:
    state = get_state(user=user, workspace_id=workspace_id)
    return {
        "providers": sorted(PROVIDERS),
        "keys": [_key_item(key) for key in state.keys],
        "allies": [_ally_item(selection) for selection in state.selections],
    }


def _write(request: HttpRequest, action):
    if rejected := _require_origin(request, allow_native_bearer=True):
        return rejected
    try:
        session = _authenticate(request)
        return action(session.user)
    except SessionInvalid:
        return error_json("session_invalid", "session invalid", 401)
    except ModelKeyInvalid:
        return error_json("validation_error", "request validation failed", 422)
    except ModelKeyMissing:
        return error_json("model_key_missing", "connect a key first", 409)
    except VaultUnavailable:
        return error_json("model_keys_unavailable", "model keys unavailable", 503)
    except (WorkspaceAccessDenied, ModelKeyUnavailable):
        return error_json("not_found", "not found", 404)


@api_controller("/workspaces/{workspace_id}", tags=["Model keys"])
class ModelKeysController(ControllerBase):
    @http_get(
        "/model-keys",
        response={200: SuccessResponse[ModelKeysResponse], **error_responses(401, 404)},
    )
    def status(self, request: HttpRequest, workspace_id: CanonicalUUID):
        return _write(
            request,
            lambda user: success_json(_state_json(user, workspace_id), "Model keys"),
        )

    @http_put(
        "/model-keys/{provider}",
        response={
            200: SuccessResponse[ModelKeysResponse],
            **error_responses(401, 404, 422, 503),
        },
    )
    def connect(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        provider: str,
        payload: ConnectKeyRequest,
    ):
        def action(user):
            connect_key(
                user=user,
                workspace_id=workspace_id,
                provider=provider,
                value=payload.key,
            )
            return success_json(_state_json(user, workspace_id), "Key connected")

        return _write(request, action)

    @http_delete(
        "/model-keys/{provider}",
        response={
            200: SuccessResponse[ModelKeysResponse],
            **error_responses(401, 404, 422),
        },
    )
    def disconnect(
        self, request: HttpRequest, workspace_id: CanonicalUUID, provider: str
    ):
        def action(user):
            disconnect_key(user=user, workspace_id=workspace_id, provider=provider)
            return success_json(_state_json(user, workspace_id), "Key disconnected")

        return _write(request, action)

    @http_put(
        "/allies/{ally_id}/model",
        response={
            200: SuccessResponse[ModelKeysResponse],
            **error_responses(401, 404, 409, 422),
        },
    )
    def select(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        ally_id: CanonicalUUID,
        payload: SelectModelRequest,
    ):
        def action(user):
            select_model(
                user=user,
                workspace_id=workspace_id,
                ally_id=ally_id,
                provider=payload.provider,
                model=payload.model,
                reasoning=payload.reasoning,
            )
            return success_json(_state_json(user, workspace_id), "Model updated")

        return _write(request, action)
