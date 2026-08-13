const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

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
  const headers = new Headers(request.headers);
  const csrf = typeof document === "undefined" ? null : readCookie(document.cookie, "csrf_token");
  if (csrf && UNSAFE_METHODS.has(request.method.toUpperCase())) {
    headers.set("X-CSRFToken", csrf);
  }
  return new Request(request, { credentials: "include", headers });
}
