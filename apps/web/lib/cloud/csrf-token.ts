import type { CloudCsrfToken, CloudError } from "@allies/cloud-client";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export interface CloudCsrfTokenOwner {
  has(): boolean;
  replace(token: CloudCsrfToken): void;
  prepare(request: Request): Request;
  clear(): void;
}

function withCredentials(request: Request, headers: Headers): Request {
  try {
    return new Request(request, { credentials: "include", headers });
  } catch {
    return new Request(request.url, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      credentials: "include",
      signal: request.signal,
    });
  }
}

export function createCloudCsrfTokenOwner(): CloudCsrfTokenOwner {
  let token: CloudCsrfToken | null = null;

  return {
    has: () => token !== null,
    replace: (nextToken) => {
      token = nextToken;
    },
    prepare: (request) => {
      const headers = new Headers(request.headers);
      if (UNSAFE_METHODS.has(request.method.toUpperCase())) {
        if (token === null) throw { kind: "security", code: "csrf_unavailable" } satisfies CloudError;
        headers.set("X-CSRFToken", token);
      }
      return withCredentials(request, headers);
    },
    clear: () => {
      token = null;
    },
  };
}
