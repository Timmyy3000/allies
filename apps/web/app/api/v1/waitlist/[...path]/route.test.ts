import { afterEach, describe, expect, it, vi } from "vitest";

import {
  handleWaitlistRequest,
  MAX_REQUEST_BODY_BYTES,
  UPSTREAM_TIMEOUT_MS,
} from "./route";

describe("waitlist facade", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("forwards an allowed waitlist request without credentials", async () => {
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_ENABLED", "true");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(input, init);
      expect(request.url).toBe("https://cloud.example.com/api/v1/waitlist/draft/configuration?source=test");
      expect(request.method).toBe("PATCH");
      expect(request.headers.get("cookie")).toBe("allies_waitlist_capability=secret; csrftoken=from-cookie");
      expect(request.headers.get("origin")).toBe("http://localhost:3000");
      expect(request.headers.get("referer")).toBe("http://localhost:3000/onboarding");
      expect(request.headers.get("x-csrftoken")).toBe("from-cookie");
      expect(request.headers.get("idempotency-key")).toBe("intent-1");
      expect(request.headers.get("authorization")).toBeNull();
      expect(await request.text()).toBe('{"revision":1}');
      return new Response(JSON.stringify({ status: "success" }), {
        status: 200,
        headers: { "content-type": "application/json", "set-cookie": "csrftoken=csrf; Path=/api/" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await handleWaitlistRequest(
      new Request("http://localhost:3000/api/v1/waitlist/draft/configuration?source=test", {
        method: "PATCH",
        headers: {
          Accept: "application/json",
          Authorization: "Bearer should-not-forward",
          Cookie: "allies_waitlist_capability=secret; csrftoken=from-cookie",
          "Content-Type": "application/json",
          "Idempotency-Key": "intent-1",
          Origin: "http://localhost:3000",
          Referer: "http://localhost:3000/onboarding",
          "X-CSRFToken": "from-client-should-not-win",
        },
        body: '{"revision":1}',
      }),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("set-cookie")).toContain("csrftoken=csrf");
    expect(await response.json()).toEqual({ status: "success" });
  });

  it("keeps bodyless draft creation bodyless", async () => {
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_ENABLED", "true");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(input, init);
      expect(request.method).toBe("POST");
      expect(request.body).toBeNull();
      return new Response(null, { status: 204 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await handleWaitlistRequest(
      new Request("http://localhost:3000/api/v1/waitlist/draft", {
        method: "POST",
        headers: { Origin: "http://localhost:3000" },
      }),
    );

    expect(response.status).toBe(204);
  });

  it("does not call Cloud when the waitlist feature is disabled", async () => {
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_ENABLED", "false");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await handleWaitlistRequest(
      new Request("http://localhost:3000/api/v1/waitlist/draft", {
        method: "POST",
        headers: { Origin: "http://localhost:3000" },
        body: "should not be read",
      }),
    );

    expect(response.status).toBe(404);
    expect(await response.json()).toMatchObject({ data: { code: "waitlist_disabled" } });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects state-changing requests from an untrusted origin", async () => {
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_ENABLED", "true");
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await handleWaitlistRequest(
      new Request("http://localhost:3000/api/v1/waitlist/draft", {
        method: "POST",
        headers: { Origin: "https://attacker.example" },
      }),
    );

    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({ data: { code: "origin_rejected" } });

    const allowed = await handleWaitlistRequest(
      new Request("http://localhost:3000/api/v1/waitlist/draft", {
        method: "POST",
        headers: {
          Origin: "http://localhost:3000",
          "X-Forwarded-For": "198.51.100.200",
        },
      }),
    );
    expect(allowed.status).toBe(204);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("enforces the configured consent version at the facade boundary", async () => {
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_ENABLED", "true");
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_CONSENT_VERSION", "waitlist-v1");
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    for (const consentVersion of [undefined, "waitlist-v0"] as const) {
      const body = JSON.stringify({
        revision: 1,
        email: "person@example.com",
        ...(consentVersion ? { consent_version: consentVersion } : {}),
      });
      const response = await handleWaitlistRequest(
        new Request("http://localhost:3000/api/v1/waitlist/draft/join", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Origin: "http://localhost:3000",
          },
          body,
        }),
      );

      expect(response.status).toBe(403);
      expect(await response.json()).toMatchObject({ data: { code: "consent_invalid" } });
    }

    const allowed = await handleWaitlistRequest(
      new Request("http://localhost:3000/api/v1/waitlist/draft/join", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Origin: "http://localhost:3000",
        },
        body: JSON.stringify({
          revision: 1,
          email: "person@example.com",
          consent_version: "waitlist-v1",
        }),
      }),
    );

    expect(allowed.status).toBe(204);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects an oversized body before reading or calling Cloud", async () => {
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_ENABLED", "true");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await handleWaitlistRequest(
      new Request("http://localhost:3000/api/v1/waitlist/draft", {
        method: "PATCH",
        headers: {
          "Content-Length": String(MAX_REQUEST_BODY_BYTES + 1),
          Origin: "http://localhost:3000",
        },
        body: "x",
      }),
    );

    expect(response.status).toBe(413);
    expect(await response.json()).toMatchObject({ data: { code: "request_too_large" } });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("caps a chunked body while it is being read", async () => {
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_ENABLED", "true");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(MAX_REQUEST_BODY_BYTES));
        controller.enqueue(new Uint8Array(1));
        controller.close();
      },
    });

    const response = await handleWaitlistRequest(
      new Request("http://localhost:3000/api/v1/waitlist/draft", {
        method: "PATCH",
        headers: { Origin: "http://localhost:3000" },
        body,
        duplex: "half",
      } as RequestInit),
    );

    expect(response.status).toBe(413);
    expect(await response.json()).toMatchObject({ data: { code: "request_too_large" } });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns a bounded timeout response when Cloud stalls", async () => {
    vi.useFakeTimers();
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_ENABLED", "true");
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const responsePromise = handleWaitlistRequest(
      new Request("http://localhost:3000/api/v1/waitlist/session"),
    );
    await vi.advanceTimersByTimeAsync(UPSTREAM_TIMEOUT_MS);
    const response = await responsePromise;

    expect(response.status).toBe(504);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("retry-after")).toBe("5");
    expect(await response.json()).toMatchObject({ data: { code: "upstream_timeout" } });
  });

});
