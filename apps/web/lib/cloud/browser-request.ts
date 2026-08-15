const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const WAITLIST_PREFIX = "/api/v1/waitlist";

function withCredentials(request: Request, headers: Headers): Request {
  try {
    return new Request(request, { credentials: "include", headers });
  } catch {
    return new Request(request.url, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      credentials: "include",
    });
  }
}

export function readCookie(cookieHeader: string, name: string): string | null {
  for (const part of cookieHeader.split(";")) {
    const [key, ...value] = part.trim().split("=");
    if (key === name) {
      try {
        return decodeURIComponent(value.join("="));
      } catch {
        return null;
      }
    }
  }
  return null;
}

export function prepareBrowserCloudRequest(request: Request): Request {
  const requestUrl = new URL(request.url);
  const isWaitlistRequest =
    requestUrl.pathname === WAITLIST_PREFIX || requestUrl.pathname.startsWith(`${WAITLIST_PREFIX}/`);
  let preparedRequest = request;

  if (isWaitlistRequest && typeof window !== "undefined") {
    const target = new URL(`${requestUrl.pathname}${requestUrl.search}`, window.location.origin);
    try {
      preparedRequest = new Request(target, request);
    } catch {
      // jsdom and the browser can expose different AbortSignal realms. Keep the
      // request body and headers when a cross-realm signal cannot be transferred.
      preparedRequest = new Request(target, {
        method: request.method,
        headers: request.headers,
        body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
        credentials: request.credentials,
      });
    }
  }

  const headers = new Headers(preparedRequest.headers);
  const csrf =
    isWaitlistRequest || typeof document === "undefined" ? null : readCookie(document.cookie, "csrf_token");
  if (csrf && UNSAFE_METHODS.has(preparedRequest.method.toUpperCase())) {
    headers.set("X-CSRFToken", csrf);
  }
  return withCredentials(preparedRequest, headers);
}
