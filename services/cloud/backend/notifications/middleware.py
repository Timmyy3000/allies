from auths.api.common import error_json


class PushRequestLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.path.startswith("/api/v1/workspaces/")
            and "/push/" in request.path
            and request.method in ("POST", "DELETE")
        ):
            try:
                length = int(request.META.get("CONTENT_LENGTH") or 0)
                if not 0 < length <= 8192:
                    return error_json("push_invalid", "push request invalid", 422)
            except ValueError:
                return error_json("push_invalid", "push request invalid", 422)
            body = request.read(8193)
            if len(body) > 8192:
                return error_json("push_invalid", "push request invalid", 422)
            request._body = body
        return self.get_response(request)
