"""HTTP boundary for native Google authorization and sessions."""

import html
import math
import secrets

from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from ninja_extra import ControllerBase, api_controller, http_get, http_post

from auths.api.common import (
    _domain_status,
    check_native_global_rate_limit,
    check_native_rate_limit,
    error_json,
    error_responses,
    success_json,
)
from auths.api.schemas import (
    NativeAuthorizationStartResponse,
    NativeLogoutRequest,
    NativeRefreshRequest,
    NativeSignInRequest,
    NativeTokenExchangeRequest,
    NativeTokenResponse,
    SuccessResponse,
)
from auths.authentication import _bearer_token
from auths.config import native_enabled
from auths.exceptions import (
    AuthDomainError,
    NativeCallbackInProgress,
    NativeIdentityUnavailable,
    SessionInvalid,
)
from auths.models import NativeCompletionMode
from auths.services.native_authorization import (
    NativeCallbackResult,
    begin_native_sign_in,
    complete_native_callback,
)
from auths.services.native_sessions import (
    exchange_native_code,
    logout_native_session,
    refresh_native_session,
)
from auths.throttle import ThrottleExceeded, ThrottleUnavailable


def _native_disabled():
    return error_json("provider_unavailable", "provider unavailable", 404)


def _no_bearer(request: HttpRequest) -> bool:
    return not request.headers.get("Authorization")


def _token_response(issued) -> NativeTokenResponse:
    now = timezone.now()
    return NativeTokenResponse(
        token_type="Bearer",
        access_token=issued.access_token,
        expires_in=max(0, math.ceil((issued.access_expires_at - now).total_seconds())),
        refresh_token=issued.refresh_token,
        refresh_expires_in=max(
            0, math.ceil((issued.refresh_expires_at - now).total_seconds())
        ),
        session_id=str(issued.family.id),
    )


def _no_store(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


def _manual_callback_response(result: NativeCallbackResult) -> HttpResponse:
    nonce = secrets.token_urlsafe(24)
    escaped_nonce = html.escape(nonce, quote=True)
    now = timezone.now()
    code_is_active = (
        result.code is not None
        and result.expires_at is not None
        and result.expires_at > now
    )
    if code_is_active:
        remaining_seconds = max(0, math.ceil((result.expires_at - now).total_seconds()))
        remaining_ms = max(0, int((result.expires_at - now).total_seconds() * 1000))
        code = html.escape(result.code, quote=True)
        body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Allies sign-in code</title>
  <style>body{{font-family:system-ui,sans-serif;line-height:1.5;margin:2rem;max-width:38rem}}code{{display:block;font:inherit;padding:.65rem;overflow-wrap:anywhere}}button{{background:#ff5800;border:0;border-radius:.5rem;color:#fff;cursor:pointer;font:inherit;margin-top:.75rem;padding:.65rem 1rem}}</style>
</head>
<body>
  <main>
    <h1>Copy your Allies sign-in code</h1>
    <p>Return to the Allies app and enter this code.</p>
    <p id="sign-in-code-label">Sign-in code</p>
    <code id="sign-in-code" tabindex="0" aria-labelledby="sign-in-code-label" aria-describedby="code-expiry">{code}</code>
    <button id="copy-sign-in-code" type="button">Copy sign-in code</button>
    <p id="copy-status" aria-live="polite">If copying is unavailable, select the code above and copy it.</p>
    <p id="code-expiry">Expires in {remaining_seconds} seconds. If it expires, start sign-in again in Allies.</p>
  </main>
  <script nonce="{escaped_nonce}">
    (() => {{
      const code = document.getElementById("sign-in-code");
      const button = document.getElementById("copy-sign-in-code");
      const status = document.getElementById("copy-status");
      const expiry = document.getElementById("code-expiry");
      const deadline = Date.now() + {remaining_ms};
      const updateExpiry = () => {{
        const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
        if (remaining === 0) {{
          code.textContent = "";
          button.disabled = true;
          status.textContent = "This code has expired. Start sign-in again in Allies.";
          expiry.textContent = "This code has expired. Start sign-in again in Allies.";
          return false;
        }}
        expiry.textContent = "Expires in " + remaining + " seconds. If it expires, start sign-in again in Allies.";
        return true;
      }};
      const selectCode = () => {{
        if (!updateExpiry()) return;
        code.focus();
        const selection = window.getSelection();
        if (selection) {{
          const range = document.createRange();
          range.selectNodeContents(code);
          selection.removeAllRanges();
          selection.addRange(range);
        }}
        status.textContent = "Copy is unavailable. Select the code and copy it.";
      }};
      updateExpiry();
      const expiryTimer = window.setInterval(() => {{
        if (!updateExpiry()) window.clearInterval(expiryTimer);
      }}, 1000);
      button.addEventListener("click", () => {{
        if (!updateExpiry()) return;
        if (!navigator.clipboard || !navigator.clipboard.writeText) {{
          selectCode();
          return;
        }}
        try {{
          navigator.clipboard.writeText(code.textContent).then(
            () => {{ status.textContent = "Copied. Return to the Allies app."; }},
            selectCode,
          );
        }} catch (error) {{
          selectCode();
        }}
      }});
    }})();
  </script>
</body>
</html>"""
    else:
        message = {
            "access_denied": "Sign-in was canceled.",
            "exchange_invalid": "This sign-in code has expired or was already used.",
            "flow_expired": "This sign-in attempt has expired.",
            "invite_required": "A beta invite is required before creating an Allies account.",
            "provider_unavailable": "The sign-in provider is temporarily unavailable.",
        }.get(
            result.error_code
            or ("exchange_invalid" if result.code is not None else None),
            "This sign-in attempt could not be completed.",
        )
        body = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Allies sign-in</title></head>
<body><main><h1>Allies sign-in</h1><p>{html.escape(message)}</p><p>Return to the Allies app and start sign-in again.</p></main></body>
</html>"""
    response = HttpResponse(body, content_type="text/html; charset=utf-8")
    _no_store(response)
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; "
        f"script-src 'nonce-{escaped_nonce}'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    )
    return response


@api_controller("/auths/native", tags=["Native Authentication"])
class NativeAuthenticationController(ControllerBase):
    @http_post(
        "/sign-in/{provider}",
        response={
            200: SuccessResponse[NativeAuthorizationStartResponse],
            **error_responses(400, 404, 429, 503),
        },
    )
    def sign_in(
        self, request: HttpRequest, provider: str, payload: NativeSignInRequest
    ):
        if not native_enabled():
            return _native_disabled()
        if not _no_bearer(request):
            return error_json("auth_unavailable", "authentication unavailable", 503)
        if payload.code_challenge_method != "S256":
            return error_json("pkce_required", "S256 PKCE is required", 400)
        try:
            check_native_rate_limit(request, "sign_in")
            start = begin_native_sign_in(
                provider=provider,
                redirect_uri=payload.redirect_uri,
                code_challenge=payload.code_challenge,
                state=payload.state,
                completion_mode=payload.completion_mode,
            )
        except ThrottleExceeded:
            return error_json("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return error_json("auth_unavailable", "authentication unavailable", 503)
        except AuthDomainError as exc:
            code = getattr(exc, "code", "provider_unavailable")
            return error_json(
                code,
                "native sign-in unavailable",
                _domain_status(code, 400),
            )
        response = success_json(
            NativeAuthorizationStartResponse(
                authorization_url=start.authorization_url,
                expires_at=start.expires_at,
            ),
            "Native sign-in started",
        )
        return _no_store(response)

    @http_get(
        "/callback/{provider}",
        response={200: None, 303: None, **error_responses(400, 404, 409, 429, 503)},
    )
    def callback(
        self,
        request: HttpRequest,
        provider: str,
        code: str = "",
        state: str = "",
        error: str = "",
    ):
        if not native_enabled():
            return _native_disabled()
        if not _no_bearer(request):
            return error_json("auth_unavailable", "authentication unavailable", 503)
        try:
            check_native_rate_limit(request, "callback")
            result = complete_native_callback(
                provider=provider,
                provider_state=state,
                provider_code=code or None,
                provider_error=error or None,
            )
        except ThrottleExceeded:
            return error_json("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return error_json("auth_unavailable", "authentication unavailable", 503)
        except NativeCallbackInProgress:
            return error_json("flow_in_progress", "authentication is in progress", 409)
        except AuthDomainError as exc:
            code = getattr(exc, "code", "flow_invalid")
            return error_json(code, "authentication failed", _domain_status(code, 400))
        if result.completion_mode is NativeCompletionMode.MANUAL_CODE:
            return _manual_callback_response(result)
        response = HttpResponse(status=303)
        response["Location"] = result.location
        return _no_store(response)

    @http_post(
        "/token",
        response={
            200: SuccessResponse[NativeTokenResponse],
            **error_responses(400, 409, 429, 503),
        },
    )
    def token(self, request: HttpRequest, payload: NativeTokenExchangeRequest):
        if not native_enabled():
            return _native_disabled()
        if not _no_bearer(request):
            return error_json("exchange_invalid", "exchange invalid", 400)
        try:
            check_native_rate_limit(request, "exchange", include_global=False)
            if payload.grant_type != "authorization_code":
                return error_json("exchange_invalid", "exchange invalid", 400)
            check_native_global_rate_limit(request)
            issued = exchange_native_code(
                code=payload.code,
                code_verifier=payload.code_verifier,
                redirect_uri=payload.redirect_uri,
            )
        except ThrottleExceeded:
            return error_json("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return error_json("auth_unavailable", "authentication unavailable", 503)
        except AuthDomainError as exc:
            code = getattr(exc, "code", "exchange_invalid")
            return error_json(code, "exchange invalid", _domain_status(code, 400))
        response = success_json(
            _token_response(issued),
            "Native session issued",
        )
        return _no_store(response)

    @http_post(
        "/token/refresh",
        response={
            200: SuccessResponse[NativeTokenResponse],
            **error_responses(401, 404, 429, 503),
        },
    )
    def refresh(self, request: HttpRequest, payload: NativeRefreshRequest):
        if not native_enabled():
            return _native_disabled()
        if not _no_bearer(request):
            return error_json("session_invalid", "session invalid", 401)
        try:
            check_native_rate_limit(request, "refresh", include_global=False)
            if payload.grant_type != "refresh_token":
                return error_json("session_invalid", "session invalid", 401)
            check_native_global_rate_limit(request)
            issued = refresh_native_session(payload.refresh_token)
        except ThrottleExceeded:
            return error_json("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return error_json("auth_unavailable", "authentication unavailable", 503)
        except NativeIdentityUnavailable:
            return error_json("auth_unavailable", "authentication unavailable", 503)
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        response = success_json(_token_response(issued), "Native session refreshed")
        return _no_store(response)

    @http_post(
        "/logout",
        response={204: None, **error_responses(401, 404, 429, 503)},
    )
    def logout(self, request: HttpRequest, payload: NativeLogoutRequest):
        if not native_enabled():
            return _native_disabled()
        try:
            check_native_rate_limit(request, "logout", include_global=False)
            try:
                access_token = _bearer_token(request)
            except SessionInvalid:
                access_token = None
            check_native_global_rate_limit(request)
            logout_native_session(
                refresh_token=payload.refresh_token,
                access_token=access_token,
            )
        except ThrottleExceeded:
            return error_json("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return error_json("auth_unavailable", "authentication unavailable", 503)
        except NativeIdentityUnavailable:
            return error_json("auth_unavailable", "authentication unavailable", 503)
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        response = HttpResponse(status=204)
        return _no_store(response)
