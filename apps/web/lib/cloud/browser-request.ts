import type { CloudCsrfTokenOwner } from "./csrf-token";

export function prepareBrowserCloudRequest(request: Request, csrf: CloudCsrfTokenOwner): Request {
  if (new URL(request.url).pathname.startsWith("/api/v1/waitlist/")) {
    return request;
  }
  return csrf.prepare(request);
}
