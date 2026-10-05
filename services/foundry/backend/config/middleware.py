from __future__ import annotations

from ipaddress import IPv4Network, IPv6Network, ip_address

from django.conf import settings


class TrustedProxyHeadersMiddleware:
    """Accept forwarded HTTPS only from explicitly configured proxy networks."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.TRUST_PROXY_HEADERS and not self._is_trusted_proxy(request):
            request.META.pop("HTTP_X_FORWARDED_PROTO", None)
        return self.get_response(request)

    @staticmethod
    def _is_trusted_proxy(request) -> bool:
        remote_addr = request.META.get("REMOTE_ADDR")
        if not remote_addr:
            return False
        try:
            address = ip_address(remote_addr)
        except ValueError:
            return False
        return any(
            address in network
            for network in settings.TRUSTED_PROXY_NETWORKS
            if isinstance(network, (IPv4Network, IPv6Network))
        )
