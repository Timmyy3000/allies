import { getWebEnvironment } from "../../../../../lib/env";

const WAITLIST_PREFIX = "/api/v1/waitlist";
export const MAX_REQUEST_BODY_BYTES = 256 * 1024;
export const UPSTREAM_TIMEOUT_MS = 10_000;
const BODY_TOO_LARGE = Symbol("body-too-large");
const RETRY_AFTER_SECONDS = "5";
const FORWARDED_REQUEST_HEADERS = [
  "accept",
  "content-type",
  "cookie",
  "idempotency-key",
  "origin",
  "referer",
  "x-csrftoken",
] as const;
const FORWARDED_RESPONSE_HEADERS = [
  "cache-control",
  "content-type",
  "etag",
  "retry-after",
  "vary",
] as const;

type HeadersWithSetCookie = Headers & { getSetCookie?: () => string[] };

function isWaitlistPath(pathname: string): boolean {
  return pathname === WAITLIST_PREFIX || pathname.startsWith(`${WAITLIST_PREFIX}/`);
}

function isStateChangingMethod(method: string): boolean {
  return method !== "GET" && method !== "HEAD";
}

function hasTrustedInterfaceOrigin(request: Request): boolean {
  const expectedOrigin = new URL(request.url).origin;
  const origin = request.headers.get("origin");
  if (origin) {
    try {
      return new URL(origin).origin === expectedOrigin;
    } catch {
      return false;
    }
  }

  const referer = request.headers.get("referer");
  if (!referer) return false;
  try {
    return new URL(referer).origin === expectedOrigin;
  } catch {
    return false;
  }
}

function readCookie(cookieHeader: string | null, name: string): string | null {
  if (!cookieHeader) return null;
  for (const part of cookieHeader.split(";")) {
    const separator = part.indexOf("=");
    if (separator < 0 || part.slice(0, separator).trim() !== name) continue;
    const value = part.slice(separator + 1).trim();
    try {
      return decodeURIComponent(value);
    } catch {
      return null;
    }
  }
  return null;
}

function requestHeaders(request: Request): Headers {
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // Cloud scopes csrftoken to /api/, so the onboarding document cannot read it
  // through document.cookie. The same-origin facade can safely derive the
  // double-submit header from the cookie on the API request itself.
  const csrf = readCookie(request.headers.get("cookie"), "csrftoken");
  if (csrf) headers.set("x-csrftoken", csrf);
  return headers;
}

function responseHeaders(upstream: Response): Headers {
  const headers = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }

  const setCookie = (upstream.headers as HeadersWithSetCookie).getSetCookie?.() ?? [];
  for (const value of setCookie) headers.append("set-cookie", value);
  if (setCookie.length === 0) {
    const combinedSetCookie = upstream.headers.get("set-cookie");
    if (combinedSetCookie) headers.append("set-cookie", combinedSetCookie);
  }

  headers.set("cache-control", "no-store");
  return headers;
}

function errorResponse(
  status: number,
  code: string,
  message: string,
  extraHeaders: Record<string, string> = {},
): Response {
  return Response.json(
    { status: "error", message, data: { code } },
    {
      status,
      headers: { "cache-control": "no-store", ...extraHeaders },
    },
  );
}

function hasExpectedJoinConsent(body: ArrayBuffer | undefined, expectedConsentVersion: string | null): boolean {
  if (!body || !expectedConsentVersion) return false;
  try {
    const parsed: unknown = JSON.parse(new TextDecoder().decode(body));
    return (
      typeof parsed === "object" &&
      parsed !== null &&
      "consent_version" in parsed &&
      (parsed as { consent_version?: unknown }).consent_version === expectedConsentVersion
    );
  } catch {
    return false;
  }
}

async function readRequestBody(request: Request): Promise<ArrayBuffer | undefined | typeof BODY_TOO_LARGE> {
  const declaredLength = request.headers.get("content-length");
  const declaredBytes = declaredLength === null ? null : Number(declaredLength);
  if (declaredBytes !== null && Number.isFinite(declaredBytes) && declaredBytes > MAX_REQUEST_BODY_BYTES) {
    return BODY_TOO_LARGE;
  }
  if (!request.body) return undefined;

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_REQUEST_BODY_BYTES) {
        await reader.cancel();
        return BODY_TOO_LARGE;
      }
      chunks.push(value);
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    throw error;
  }

  if (total === 0) return undefined;
  const body = new ArrayBuffer(total);
  const view = new Uint8Array(body);
  let offset = 0;
  for (const chunk of chunks) {
    view.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

export async function handleWaitlistRequest(request: Request): Promise<Response> {
  // Cloud owns distributed waitlist admission and generation budgets. Keep the
  // facade free of a spoofable, per-instance identity limiter and enforce only
  // same-origin and consent boundaries before forwarding to that authority.
  // CLD-008 consumes global and capability budgets around greeting generation;
  // those controls remain authoritative when the waitlist is enabled.
  const requestUrl = new URL(request.url);
  if (!isWaitlistPath(requestUrl.pathname)) {
    return Response.json({ status: "error", message: "Not found" }, { status: 404 });
  }

  const environment = getWebEnvironment();
  if (!environment.waitlistEnabled) {
    return errorResponse(404, "waitlist_disabled", "Not found");
  }
  if (!environment.cloudApiUrl) {
    return errorResponse(503, "waitlist_unavailable", "Waitlist service unavailable", {
      "retry-after": RETRY_AFTER_SECONDS,
    });
  }

  if (isStateChangingMethod(request.method) && !hasTrustedInterfaceOrigin(request)) {
    return errorResponse(403, "origin_rejected", "Request origin is not allowed.");
  }

  let body: ArrayBuffer | undefined;
  if (isStateChangingMethod(request.method)) {
    try {
      const candidate = await readRequestBody(request);
      if (candidate === BODY_TOO_LARGE) {
        return errorResponse(413, "request_too_large", "Request body is too large");
      }
      body = candidate;
    } catch {
      return errorResponse(400, "request_body_invalid", "Request body could not be read");
    }
  }

  if (
    request.method === "POST" &&
    requestUrl.pathname === `${WAITLIST_PREFIX}/draft/join` &&
    !hasExpectedJoinConsent(body, environment.waitlistConsentVersion)
  ) {
    return errorResponse(403, "consent_invalid", "Waitlist consent is not available.");
  }

  const { cloudApiUrl } = environment;
  const upstreamUrl = new URL(`${requestUrl.pathname}${requestUrl.search}`, cloudApiUrl);
  let upstream: Response;
  const controller = new AbortController();
  let timedOut = false;
  const abortForCaller = () => controller.abort(request.signal.reason);
  if (request.signal.aborted) abortForCaller();
  request.signal.addEventListener("abort", abortForCaller, { once: true });
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, UPSTREAM_TIMEOUT_MS);
  try {
    upstream = await fetch(upstreamUrl, {
      method: request.method,
      headers: requestHeaders(request),
      body,
      cache: "no-store",
      redirect: "manual",
      signal: controller.signal,
    });
  } catch {
    return timedOut
      ? errorResponse(504, "upstream_timeout", "Waitlist service timed out", {
          "retry-after": RETRY_AFTER_SECONDS,
        })
      : errorResponse(503, "upstream_unavailable", "Waitlist service unavailable", {
          "retry-after": RETRY_AFTER_SECONDS,
        });
  } finally {
    clearTimeout(timeout);
    request.signal.removeEventListener("abort", abortForCaller);
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders(upstream),
  });
}

export const GET = handleWaitlistRequest;
export const POST = handleWaitlistRequest;
export const PATCH = handleWaitlistRequest;
