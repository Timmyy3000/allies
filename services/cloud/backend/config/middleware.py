import ipaddress
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

CANONICAL_CLIENT_ADDRESS_META = "ALLIES_CANONICAL_CLIENT_ADDRESS"


def canonical_client_address(request: HttpRequest) -> str | None:
    """Return a bounded network prefix from a trusted request boundary."""

    if getattr(settings, "ALLIES_RAILWAY_PROXY_MODE", False):
        return None
    peer = str(request.META.get("REMOTE_ADDR", "")).strip()[:128]
    raw = peer
    trusted = set(getattr(settings, "ALLIES_TRUSTED_PROXY_IPS", ()))
    if getattr(settings, "ALLIES_TRUST_FORWARDED_FOR", False) and peer in trusted:
        chain = [
            item.strip()[:128]
            for item in str(request.META.get("HTTP_X_FORWARDED_FOR", ""))[:4096].split(
                ","
            )
            if item.strip()
        ] + [peer]
        while chain and chain[-1] in trusted:
            chain.pop()
        if chain:
            raw = chain[-1]
    try:
        address = ipaddress.ip_address(raw)
        prefix = 24 if address.version == 4 else 64
        return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))
    except ValueError:
        return None


class TrustedProxyHeadersMiddleware:
    """Normalize proxy headers at the configured deployment trust boundary."""

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
            # and client-address signals from its managed edge.
            forwarded_proto = request.META.get("HTTP_X_FORWARDED_PROTO", "")
            for header in self.forwarded_headers:
                if header != "HTTP_X_FORWARDED_PROTO":
                    request.META.pop(header, None)
            if forwarded_proto != "https":
                # Keep a concrete non-HTTPS value for SecurityMiddleware. If
                # the header were removed, Django's request handling could
                # reinsert its secure fallback before redirect evaluation.
                request.META["HTTP_X_FORWARDED_PROTO"] = "http"
            request.META.pop(CANONICAL_CLIENT_ADDRESS_META, None)
            return self.get_response(request)
        trusted = set(getattr(settings, "ALLIES_TRUSTED_PROXY_IPS", ()))
        if request.META.get("REMOTE_ADDR", "") not in trusted:
            for header in self.forwarded_headers:
                request.META.pop(header, None)
        canonical = canonical_client_address(request)
        if canonical is None:
            request.META.pop(CANONICAL_CLIENT_ADDRESS_META, None)
        else:
            request.META[CANONICAL_CLIENT_ADDRESS_META] = canonical
        return self.get_response(request)
