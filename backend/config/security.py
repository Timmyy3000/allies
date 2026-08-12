from django.core.exceptions import DisallowedHost
from django.middleware.security import SecurityMiddleware

RAILWAY_HEALTHCHECK_HOST = "healthcheck.railway.app"
RAILWAY_HEALTHCHECK_USER_AGENT = "RailwayHealthCheck/1.0"


class RailwayHealthcheckSecurityMiddleware(SecurityMiddleware):
    """Keep Railway's internal HTTP readiness probe off the HTTPS redirect.

    Railway's probe shares the service listener with application traffic, so
    the host and user-agent checks are routing guards, not authentication. The
    endpoint intentionally returns only non-sensitive readiness status.
    """

    def process_request(self, request):
        if self._is_railway_healthcheck(request):
            return None
        return super().process_request(request)

    @staticmethod
    def _is_railway_healthcheck(request):
        if request.path != "/healthz":
            return False
        if request.META.get("HTTP_USER_AGENT") != RAILWAY_HEALTHCHECK_USER_AGENT:
            return False
        try:
            return request.get_host().split(":", 1)[0].lower() == RAILWAY_HEALTHCHECK_HOST
        except DisallowedHost:
            return False
