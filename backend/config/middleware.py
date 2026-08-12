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
        trusted = set(getattr(settings, "ALLIES_TRUSTED_PROXY_IPS", ()))
        if request.META.get("REMOTE_ADDR", "") not in trusted:
            for header in self.forwarded_headers:
                request.META.pop(header, None)
        return self.get_response(request)
