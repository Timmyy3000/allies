from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse


class TrustedProxyHeadersMiddleware:
    """Remove proxy-controlled headers unless the direct peer is trusted."""

    forwarded_headers = (
        "HTTP_X_FORWARDED_FOR",
        "HTTP_X_FORWARDED_HOST",
        "HTTP_X_FORWARDED_PROTO",
    )

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if getattr(settings, "ALLIES_RAILWAY_PROXY_MODE", False):
            # Railway has no public TCP ingress; only preserve the exact HTTPS
            # signal from its managed edge. Never trust identity or host data.
            forwarded_proto = request.META.get("HTTP_X_FORWARDED_PROTO", "")
            for header in self.forwarded_headers:
                if header != "HTTP_X_FORWARDED_PROTO":
                    request.META.pop(header, None)
            if forwarded_proto != "https":
                # Keep a concrete non-HTTPS value for SecurityMiddleware. If
                # the header were removed, Django's request handling could
                # reinsert its secure fallback before redirect evaluation.
                request.META["HTTP_X_FORWARDED_PROTO"] = "http"
            return self.get_response(request)
        trusted = set(getattr(settings, "ALLIES_TRUSTED_PROXY_IPS", ()))
        if request.META.get("REMOTE_ADDR", "") not in trusted:
            for header in self.forwarded_headers:
                request.META.pop(header, None)
        return self.get_response(request)
