"""Google integration (Gmail, Calendar) connection, grant, and disconnect routes.

Interface talks to Cloud only. Every route resolves the workspace through
live membership plus capability; grant rows are re-read per dispatch and
never cached. Secrets and tokens never appear in responses.
"""

from typing import Annotated
from urllib.parse import urlencode, urlsplit, urlunsplit

from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from ninja import Header, Query
from ninja_extra import ControllerBase, api_controller, http_delete, http_get, http_post

from allies.models import Ally
from auths.api.common import (
    _request_origin,
    _require_origin,
    _session,
    error_json,
    error_responses,
    success_json,
)
from auths.api.schemas import SuccessResponse
from auths.exceptions import InvalidRedirect, SessionInvalid, WorkspaceAccessDenied
from auths.services.flows import _safe_redirect
from common.uuids import CanonicalUUID
from integrations.api.schemas import (
    AllyGrantResponse,
    BeginConnectRequest,
    ConnectResponse,
    DisconnectRequest,
    DisconnectResponse,
    GmailConnectionResponse,
    SetGrantRequest,
)
from integrations.exceptions import (
    GrantDenied,
    IntegrationConflict,
    IntegrationInvalid,
    IntegrationUnavailable,
    ProviderUnavailable,
    RefreshRevoked,
    ScopeInsufficient,
)
from integrations.models import PROVIDER_CALENDAR, PROVIDER_GMAIL, IntegrationSecret
from integrations.services import google_oauth
from integrations.services.grants import (
    disconnect_account,
    revoke_ally_grant,
    set_ally_grant,
)
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability


def _ally_in_workspace(workspace_id, ally_id) -> Ally:
    try:
        return Ally.objects.get(id=ally_id, workspace_id=workspace_id)
    except Ally.DoesNotExist as exc:
        raise IntegrationInvalid("ally is unknown in this workspace") from exc


def _live_secret(workspace_id, provider):
    return (
        IntegrationSecret.objects.filter(
            workspace_id=workspace_id,
            provider_key=provider,
            revoked_at=None,
        )
        .order_by("-connected_at")
        .first()
    )


def _connection_response(secret: IntegrationSecret) -> GmailConnectionResponse:
    grants = [
        AllyGrantResponse(
            ally_id=grant.ally_id,
            level=grant.level,
            grant_generation=grant.grant_generation,
            updated_at=grant.updated_at,
        )
        for grant in secret.ally_grants.select_related("ally").order_by("ally_id")
    ]
    return GmailConnectionResponse(
        connection_id=secret.id,
        account_email=secret.account_email,
        scope_set=list(secret.scope_set or []),
        connected_at=secret.connected_at,
        ally_grants=grants,
    )


def _redirect_with(target: str, **params: str) -> HttpResponse:
    parsed = urlsplit(target)
    extra = urlencode(params)
    query = f"{parsed.query}&{extra}" if parsed.query else extra
    response = HttpResponse(status=303)
    response["Location"] = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment)
    )
    response["Referrer-Policy"] = "no-referrer"
    return response


def _error_code(response) -> str:
    import json

    try:
        return json.loads(response.content)["data"]["code"]
    except (ValueError, KeyError, TypeError):
        return "internal_error"


def _read_error(exc: Exception):
    if isinstance(exc, SessionInvalid):
        return error_json("session_invalid", "session invalid", 401)
    if isinstance(exc, WorkspaceAccessDenied):
        return error_json("workspace_unavailable", "workspace unavailable", 404)
    if isinstance(exc, ScopeInsufficient):
        return error_json(
            "scope_insufficient", "google access was not fully granted", 422
        )
    if isinstance(exc, IntegrationInvalid):
        return error_json("validation_error", "request validation failed", 422)
    if isinstance(exc, GrantDenied):
        return error_json("grant_denied", "ally access denied", 403)
    if isinstance(exc, IntegrationConflict):
        return error_json("integration_conflict", "request conflicts", 409)
    if isinstance(exc, RefreshRevoked):
        return error_json("refresh_revoked", "connection revoked", 409)
    if isinstance(exc, (IntegrationUnavailable, ProviderUnavailable)):
        return error_json(
            "provider_unavailable", "provider temporarily unavailable", 503
        )
    if isinstance(exc, DatabaseError):
        return error_json("internal_error", "internal server error", 500)
    return None


def _integration_controller(provider_key: str, name: str):
    class Controller(ControllerBase):
        provider = provider_key

        @http_get(
            "",
            response={
                200: SuccessResponse[GmailConnectionResponse | None],
                **error_responses(401, 404, 422, 500),
            },
        )
        def status(self, request: HttpRequest, workspace_id: CanonicalUUID):
            try:
                session = _session(request)
                require_workspace_capability(
                    user=session.user,
                    workspace_id=workspace_id,
                    capability=Capability.WORKSPACE_READ,
                )
                secret = _live_secret(workspace_id, self.provider)
                data = _connection_response(secret) if secret else None
            except Exception as exc:
                response = _read_error(exc)
                if response is not None:
                    return response
                raise
            return success_json(data, "Connection status")

        @http_post(
            "/connect",
            response={
                200: SuccessResponse[ConnectResponse],
                202: SuccessResponse[ConnectResponse],
                **error_responses(401, 403, 404, 409, 422, 503, 500),
            },
        )
        def begin(
            self,
            request: HttpRequest,
            workspace_id: CanonicalUUID,
            payload: BeginConnectRequest,
            idempotency_key: Annotated[
                str,
                Header(alias="Idempotency-Key", min_length=16, max_length=128),
            ],
        ):
            if rejected := _require_origin(request, allow_native_bearer=True):
                return rejected
            try:
                session = _session(request)
                context = require_workspace_capability(
                    user=session.user,
                    workspace_id=workspace_id,
                    capability=Capability.WORKSPACE_WRITE,
                )
                return_to = None
                if payload.return_to is not None:
                    try:
                        return_to = _safe_redirect(
                            payload.return_to, _request_origin(request)
                        )
                    except InvalidRedirect as exc:
                        raise IntegrationInvalid("return target is invalid") from exc
                ally = None
                if payload.entry_point == "in_chat":
                    if payload.ally_id is None:
                        raise IntegrationInvalid("in-chat connect requires an ally")
                    ally = _ally_in_workspace(context.workspace.id, payload.ally_id)
                begun = google_oauth.begin_connect(
                    workspace=context.workspace,
                    provider=self.provider,
                    entry_point=payload.entry_point,
                    ally=ally,
                    grant_level=payload.grant_level,
                    idempotency_key=idempotency_key,
                    return_to=return_to,
                )
            except Exception as exc:
                response = _read_error(exc)
                if response is not None:
                    return response
                raise
            return success_json(
                ConnectResponse(
                    connect_session_id=begun.connect_session_id,
                    auth_url=begun.auth_url,
                    expires_at=begun.expires_at,
                ),
                "Connect started",
                status=202,
            )

        @http_post(
            "/grants",
            response={
                200: SuccessResponse[AllyGrantResponse],
                **error_responses(401, 403, 404, 409, 422, 503, 500),
            },
        )
        def set_grant(
            self,
            request: HttpRequest,
            workspace_id: CanonicalUUID,
            payload: SetGrantRequest,
        ):
            if rejected := _require_origin(request, allow_native_bearer=True):
                return rejected
            try:
                session = _session(request)
                context = require_workspace_capability(
                    user=session.user,
                    workspace_id=workspace_id,
                    capability=Capability.WORKSPACE_WRITE,
                )
                secret = _live_secret(context.workspace.id, self.provider)
                if secret is None:
                    raise IntegrationInvalid("not connected")
                ally = _ally_in_workspace(context.workspace.id, payload.ally_id)
                if payload.level == "none":
                    revoke_ally_grant(secret=secret, ally=ally)
                    grant = None
                else:
                    grant = set_ally_grant(
                        secret=secret,
                        ally=ally,
                        level=payload.level,
                        created_by=session.user,
                    )
            except Exception as exc:
                response = _read_error(exc)
                if response is not None:
                    return response
                raise
            if grant is None:
                return success_json(
                    AllyGrantResponse(
                        ally_id=payload.ally_id,
                        level="none",
                        grant_generation=0,
                        updated_at=secret.connected_at,
                    ),
                    "Ally grant removed",
                )
            return success_json(
                AllyGrantResponse(
                    ally_id=grant.ally_id,
                    level=grant.level,
                    grant_generation=grant.grant_generation,
                    updated_at=grant.updated_at,
                ),
                "Ally grant saved",
            )

        @http_delete(
            "",
            response={
                202: SuccessResponse[DisconnectResponse],
                **error_responses(401, 403, 404, 409, 422, 503, 500),
            },
        )
        def disconnect(
            self,
            request: HttpRequest,
            workspace_id: CanonicalUUID,
            payload: DisconnectRequest,
        ):
            if rejected := _require_origin(request, allow_native_bearer=True):
                return rejected
            try:
                session = _session(request)
                context = require_workspace_capability(
                    user=session.user,
                    workspace_id=workspace_id,
                    capability=Capability.WORKSPACE_WRITE,
                )
                if not payload.confirm:
                    raise IntegrationInvalid("disconnect requires confirmation")
                secret = (
                    IntegrationSecret.objects.filter(
                        workspace_id=context.workspace.id,
                        provider_key=self.provider,
                    )
                    .order_by("-connected_at")
                    .first()
                )
                if secret is None or (
                    secret.revoked_at is not None and not bytes(secret.ciphertext)
                ):
                    result_status = "already_cleaned"
                else:
                    result = disconnect_account(secret=secret)
                    result_status = result.status
            except Exception as exc:
                response = _read_error(exc)
                if response is not None:
                    return response
                raise
            if result_status == "repair_required":
                return error_json("repair_required", "disconnect needs repair", 409)
            return success_json(
                DisconnectResponse(status=result_status),
                "Disconnect accepted",
                status=202,
            )

    Controller.__name__ = f"{name}Controller"
    return api_controller(
        f"/workspaces/{{workspace_id}}/integrations/{name.lower()}",
        tags=["Integrations"],
    )(Controller)


GmailController = _integration_controller(PROVIDER_GMAIL, "Gmail")
CalendarController = _integration_controller(PROVIDER_CALENDAR, "Calendar")


@api_controller("/integrations/gmail", tags=["Integrations"])
class GmailCallbackController(ControllerBase):
    @http_get(
        "/callback",
        response={
            200: SuccessResponse[GmailConnectionResponse],
            303: None,
            **error_responses(401, 404, 409, 422, 503, 500),
        },
    )
    def callback(
        self,
        request: HttpRequest,
        code: str = Query("", max_length=2048),
        state: str = Query("", max_length=256),
        error: str = Query("", max_length=64),
    ):
        # Interface clients that sent return_to get a redirect back with the
        # outcome, like sign-in; older clients keep the JSON response.
        return_to = google_oauth.connect_return_to(state=state)
        provider = google_oauth.connect_provider(state=state)
        if error or not code or not state:
            reason = "access_denied" if error == "access_denied" else "validation_error"
            if return_to:
                return _redirect_with(return_to, **{f"{provider}_error": reason})
            return error_json(reason, "connect was not completed", 422)
        # Browser navigation returning from Google carries no trusted origin
        # or CSRF token. The one-time state token plus the session cookie is
        # the authorization for this single exchange. Workspace capability is
        # enforced before any mutation: the pending session resolves the
        # workspace without consuming it.
        try:
            session = _session(request)
            workspace_id = google_oauth.peek_connect_session(state=state).workspace_id
            require_workspace_capability(
                user=session.user,
                workspace_id=workspace_id,
                capability=Capability.WORKSPACE_WRITE,
            )
            completed = google_oauth.complete_connect(state=state, code=code)
            if (
                completed.auto_grant_ally_id is not None
                and completed.auto_grant_level is not None
            ):
                ally = _ally_in_workspace(
                    completed.secret.workspace_id, completed.auto_grant_ally_id
                )
                set_ally_grant(
                    secret=completed.secret,
                    ally=ally,
                    level=completed.auto_grant_level,
                    created_by=session.user,
                )
            data = _connection_response(completed.secret)
        except Exception as exc:
            response = _read_error(exc)
            if response is not None:
                if return_to:
                    return _redirect_with(
                        return_to, **{f"{provider}_error": _error_code(response)}
                    )
                return response
            raise
        if return_to:
            return _redirect_with(return_to, **{provider: "connected"})
        return success_json(data, "Connected")
