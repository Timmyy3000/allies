"""Explicit HTTP controllers for the passwordless Cloud boundary."""

import ipaddress

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import (
    InvalidTokenFormat,
    _check_token_format,
    _does_token_match,
    get_token,
)
from django.utils import timezone
from ninja_extra import (
    ControllerBase,
    api_controller,
    http_delete,
    http_get,
    http_patch,
    http_post,
)

from auths.api.schemas import (
    AuthorizationStartResponse,
    AvatarPrepareRequest,
    AvatarResponse,
    MeResponse,
    PreparedAvatarResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    RedirectRequest,
)
from auths.config import (
    access_ttl_seconds,
    cookie_name,
    cookie_path,
    cookie_samesite,
    cookie_secure,
    flow_ttl_seconds,
)
from auths.exceptions import AuthDomainError, SessionInvalid
from auths.models import FlowPurpose
from auths.providers.base import ProviderKey
from auths.services.avatars import (
    complete_avatar_upload,
    delete_current_avatar,
    prepare_avatar_upload,
    signed_avatar_read,
)
from auths.services.flows import (
    begin_auth_flow,
    complete_auth_flow,
    flow_redirect_for_state,
)
from auths.services.profiles import get_self_profile, update_display_name
from auths.services.sessions import (
    authenticate_access,
    logout_session,
    refresh_family_public_id,
    rotate_refresh,
)
from auths.throttle import ThrottleExceeded, ThrottleUnavailable, check_rate_limit


def _error(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def _domain_status(code: str, default: int = 400) -> int:
    return {
        "provider_unavailable": 404,
        "already_linked_elsewhere": 409,
        "storage_unavailable": 503,
        "throttle_unavailable": 503,
        "avatar_absent": 404,
        "invalid_state": 409,
    }.get(code, default)


def _origin_allowed(request: HttpRequest) -> bool:
    origin = request.headers.get("Origin")
    if not origin:
        referer = request.headers.get("Referer")
        if not referer:
            return False
        origin = referer.split("/", 3)[:3]
        origin = "/".join(origin)
    allowed = set(getattr(settings, "CSRF_TRUSTED_ORIGINS", ()))
    return origin in allowed


def _require_origin(request: HttpRequest) -> JsonResponse | None:
    if not _origin_allowed(request):
        return _error("origin_rejected", "origin rejected", 403)
    csrf_name = getattr(settings, "CSRF_COOKIE_NAME", "csrftoken")
    cookie = request.COOKIES.get(csrf_name)
    header = request.headers.get("X-CSRFToken")
    try:
        if not cookie or not header:
            raise InvalidTokenFormat("missing CSRF token")
        _check_token_format(cookie)
        _check_token_format(header)
        valid = _does_token_match(header, cookie)
    except (InvalidTokenFormat, AssertionError):
        valid = False
    if not valid:
        return _error("csrf_rejected", "csrf rejected", 403)
    return None


def _session(request: HttpRequest):
    raw = request.COOKIES.get(cookie_name("access"))
    if not raw:
        raise SessionInvalid("session invalid")
    return authenticate_access(raw)


def _csrf_binding(request: HttpRequest) -> bytes:
    name = getattr(settings, "CSRF_COOKIE_NAME", "csrftoken")
    return (request.COOKIES.get(name) or "").encode()


def _client_identity(request: HttpRequest) -> str:
    peer = request.META.get("REMOTE_ADDR", "").strip()
    raw = peer
    trusted = set(getattr(settings, "ALLIES_TRUSTED_PROXY_IPS", ()))
    if getattr(settings, "ALLIES_TRUST_FORWARDED_FOR", False) and peer in trusted:
        chain = [
            item.strip()
            for item in request.headers.get("X-Forwarded-For", "").split(",")
            if item.strip()
        ] + [peer]
        while chain and chain[-1] in trusted:
            chain.pop()
        if chain:
            raw = chain[-1]
    # Correlation is intentionally limited to a coarse network and HMAC-keyed
    # before it reaches the cache.
    try:
        address = ipaddress.ip_address(raw)
        prefix = 24 if address.version == 4 else 64
        return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))
    except ValueError:
        return "unknown"


def _set_session_cookies(response: HttpResponse, issued) -> None:
    response.set_cookie(
        cookie_name("access"),
        issued.access_token,
        max_age=access_ttl_seconds(),
        httponly=True,
        secure=cookie_secure(),
        samesite=cookie_samesite(),
        path=cookie_path("access"),
    )
    response.set_cookie(
        cookie_name("refresh"),
        issued.refresh_token,
        max_age=max(
            0, int((issued.refresh_expires_at - timezone.now()).total_seconds())
        ),
        httponly=True,
        secure=cookie_secure(),
        samesite="Strict",
        path=cookie_path("refresh"),
    )


def _clear_auth_cookies(response: HttpResponse) -> None:
    response.delete_cookie(cookie_name("access"), path=cookie_path("access"))
    response.delete_cookie(cookie_name("refresh"), path=cookie_path("refresh"))
    response.delete_cookie(cookie_name("flow"), path=cookie_path("flow"))


@api_controller("/auths", tags=["auths"])
class AuthController(ControllerBase):
    @http_get("/csrf")
    def csrf(self, request: HttpRequest):
        response = HttpResponse(status=204)
        response["X-CSRFToken"] = get_token(request)
        return response

    @http_post("/sign-in/{provider}")
    def sign_in(self, request: HttpRequest, provider: str, payload: RedirectRequest):
        rejected = _require_origin(request)
        if rejected:
            return rejected
        try:
            check_rate_limit(
                scope="sign-in",
                identity=f"{_client_identity(request)}:{provider}",
                limit=10,
                period=60,
            )
        except ThrottleExceeded:
            return _error("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return _error("throttle_unavailable", "authentication unavailable", 503)
        binding_bytes = _csrf_binding(request)
        try:
            start = begin_auth_flow(
                provider=ProviderKey(provider),
                purpose=FlowPurpose.SIGN_IN,
                redirect_to=payload.redirect_to,
                browser_binding=binding_bytes,
            )
        except (AuthDomainError, ValueError) as exc:
            code = getattr(exc, "code", "provider_unavailable")
            return _error(code, "sign-in unavailable", _domain_status(code))
        response = JsonResponse(
            AuthorizationStartResponse(
                redirect_url=start.authorization_url
            ).model_dump()
        )
        response.set_cookie(
            cookie_name("flow"),
            start.flow_cookie,
            max_age=max(0, int((start.expires_at - timezone.now()).total_seconds())),
            httponly=True,
            secure=cookie_secure(),
            samesite=cookie_samesite(),
            path=cookie_path("flow"),
        )
        return response

    @http_post("/identities/{provider}/link")
    def link(self, request: HttpRequest, provider: str, payload: RedirectRequest):
        rejected = _require_origin(request)
        if rejected:
            return rejected
        try:
            session = _session(request)
            check_rate_limit(
                scope="link",
                identity=f"{session.actor.public_id}:{provider}",
                limit=5,
                period=3600,
            )
            start = begin_auth_flow(
                provider=ProviderKey(provider),
                purpose=FlowPurpose.LINK,
                redirect_to=payload.redirect_to,
                browser_binding=_csrf_binding(request),
                actor=session.actor,
                family=session.family,
            )
        except ThrottleExceeded:
            return _error("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return _error("throttle_unavailable", "authentication unavailable", 503)
        except (AuthDomainError, ValueError) as exc:
            code = getattr(exc, "code", "session_invalid")
            return _error(code, "link unavailable", _domain_status(code, 401))
        response = JsonResponse(
            AuthorizationStartResponse(
                redirect_url=start.authorization_url
            ).model_dump()
        )
        response.set_cookie(
            cookie_name("flow"),
            start.flow_cookie,
            max_age=flow_ttl_seconds(),
            httponly=True,
            secure=cookie_secure(),
            samesite=cookie_samesite(),
            path=cookie_path("flow"),
        )
        return response

    @http_get("/callback/{provider}")
    def callback(
        self, request: HttpRequest, provider: str, code: str = "", state: str = ""
    ):
        flow_cookie = request.COOKIES.get(cookie_name("flow"))
        binding = _csrf_binding(request)
        try:
            completion = complete_auth_flow(
                provider=ProviderKey(provider),
                state=state,
                code=code,
                browser_binding=binding,
                flow_cookie=flow_cookie,
            )
        except (AuthDomainError, ValueError) as exc:
            code = getattr(exc, "code", "flow_invalid")
            target = flow_redirect_for_state(state)
            if target:
                separator = "&" if "?" in target else "?"
                response = HttpResponse(status=303)
                response["Location"] = f"{target}{separator}auth_error={code}"
                response.delete_cookie(cookie_name("flow"), path=cookie_path("flow"))
                return response
            return _error(code, "authentication failed", _domain_status(code))
        response = HttpResponse(status=303)
        response["Location"] = completion.redirect_to
        if completion.session:
            _set_session_cookies(response, completion.session)
        response.delete_cookie(cookie_name("flow"), path=cookie_path("flow"))
        return response

    @http_post("/refresh")
    def refresh(self, request: HttpRequest):
        rejected = _require_origin(request)
        if rejected:
            return rejected
        raw = request.COOKIES.get(cookie_name("refresh"))
        if not raw:
            return _error("session_invalid", "session invalid", 401)
        try:
            check_rate_limit(
                scope="refresh-ip",
                identity=_client_identity(request),
                limit=20,
                period=60,
            )
            family_id = refresh_family_public_id(raw)
            check_rate_limit(
                scope="refresh-family",
                identity=family_id,
                limit=20,
                period=60,
            )
        except ThrottleExceeded:
            return _error("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return _error("throttle_unavailable", "authentication unavailable", 503)
        except SessionInvalid:
            return _error("session_invalid", "session invalid", 401)
        try:
            issued = rotate_refresh(raw)
        except SessionInvalid:
            return _error("session_invalid", "session invalid", 401)
        response = HttpResponse(status=204)
        _set_session_cookies(response, issued)
        return response

    @http_post("/logout")
    def logout(self, request: HttpRequest):
        rejected = _require_origin(request)
        if rejected:
            return rejected
        access = None
        try:
            if request.COOKIES.get(cookie_name("access")):
                access = authenticate_access(request.COOKIES[cookie_name("access")])
        except SessionInvalid:
            access = None
        logout_session(
            access=access, refresh=request.COOKIES.get(cookie_name("refresh"))
        )
        response = HttpResponse(status=204)
        _clear_auth_cookies(response)
        return response

    @http_get("/me")
    def me(self, request: HttpRequest):
        try:
            result = get_self_profile(_session(request))
        except (AuthDomainError, SessionInvalid):
            return _error("session_invalid", "session invalid", 401)
        return JsonResponse(
            MeResponse(
                actor={"id": result.actor_id},
                profile=ProfileResponse(
                    display_name=result.profile.display_name,
                    avatar_url=result.profile.avatar_url,
                ),
                session={
                    "id": result.session.id,
                    "expires_at": result.session.expires_at,
                },
                workspace={
                    "id": result.workspace.id,
                    "name": result.workspace.name,
                    "role": result.workspace.role,
                    "capabilities": list(result.workspace.capabilities),
                },
            ).model_dump(mode="json")
        )

    @http_patch("/me/profile")
    def profile(self, request: HttpRequest, payload: ProfileUpdateRequest):
        rejected = _require_origin(request)
        if rejected:
            return rejected
        try:
            session = _session(request)
            profile = update_display_name(session.actor, payload.display_name)
        except SessionInvalid:
            return _error("session_invalid", "session invalid", 401)
        except AuthDomainError as exc:
            return _error(
                getattr(exc, "code", "validation_error"), "profile update invalid", 422
            )
        return JsonResponse(
            ProfileResponse(display_name=profile.display_name).model_dump()
        )

    @http_post("/me/avatar/uploads")
    def avatar_prepare(self, request: HttpRequest, payload: AvatarPrepareRequest):
        rejected = _require_origin(request)
        if rejected:
            return rejected
        try:
            session = _session(request)
            check_rate_limit(
                scope="avatar-prepare",
                identity=session.actor.public_id,
                limit=10,
                period=3600,
            )
            prepared = prepare_avatar_upload(
                actor=session.actor,
                content_type=payload.content_type,
                size=payload.size,
                sha256=payload.sha256,
            )
        except ThrottleExceeded:
            return _error("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return _error("throttle_unavailable", "storage unavailable", 503)
        except SessionInvalid:
            return _error("session_invalid", "session invalid", 401)
        except RuntimeError:
            return _error("storage_unavailable", "avatar storage unavailable", 503)
        except AuthDomainError as exc:
            code = getattr(exc, "code", "validation_error")
            return _error(code, "avatar request invalid", _domain_status(code, 422))
        return JsonResponse(
            PreparedAvatarResponse(
                asset_id=prepared.asset.public_id,
                upload_url=prepared.upload_url,
                headers=prepared.headers,
                expires_at=prepared.expires_at,
            ).model_dump(mode="json"),
            status=201,
        )

    @http_post("/me/avatar/{asset_id}/complete")
    def avatar_complete(self, request: HttpRequest, asset_id: str):
        rejected = _require_origin(request)
        if rejected:
            return rejected
        try:
            session = _session(request)
            check_rate_limit(
                scope="avatar-complete",
                identity=session.actor.public_id,
                limit=20,
                period=3600,
            )
            ready = complete_avatar_upload(actor=session.actor, asset_id=asset_id)
            url, expires = signed_avatar_read(actor=session.actor)
        except ThrottleExceeded:
            return _error("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return _error("throttle_unavailable", "storage unavailable", 503)
        except SessionInvalid:
            return _error("session_invalid", "session invalid", 401)
        except RuntimeError:
            return _error("storage_unavailable", "avatar storage unavailable", 503)
        except AuthDomainError as exc:
            code = getattr(exc, "code", "avatar_invalid")
            return _error(code, "avatar unavailable", _domain_status(code, 422))
        return JsonResponse(
            AvatarResponse(
                asset_id=ready.asset.public_id, url=url, expires_at=expires
            ).model_dump(mode="json")
        )

    @http_get("/me/avatar/read")
    def avatar_read(self, request: HttpRequest):
        try:
            session = _session(request)
            url, expires = signed_avatar_read(actor=session.actor)
        except SessionInvalid:
            return _error("session_invalid", "session invalid", 401)
        except RuntimeError:
            return _error("storage_unavailable", "avatar storage unavailable", 503)
        except AuthDomainError as exc:
            code = getattr(exc, "code", "avatar_absent")
            return _error(code, "avatar unavailable", _domain_status(code, 404))
        return JsonResponse(
            AvatarResponse(asset_id="", url=url, expires_at=expires).model_dump(
                mode="json"
            )
        )

    @http_delete("/me/avatar")
    def avatar_delete(self, request: HttpRequest):
        rejected = _require_origin(request)
        if rejected:
            return rejected
        try:
            session = _session(request)
            delete_current_avatar(session.actor)
        except SessionInvalid:
            return _error("session_invalid", "session invalid", 401)
        except AuthDomainError as exc:
            code = getattr(exc, "code", "avatar_invalid")
            return _error(code, "avatar unavailable", _domain_status(code, 409))
        return HttpResponse(status=204)
