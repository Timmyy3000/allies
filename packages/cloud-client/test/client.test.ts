import { describe, expect, it, vi } from "vitest";

import { createCloudClient, parseSafeReturnPath } from "../src/client";
import { defineApiFixture } from "./fixtures";

const accountResponse = defineApiFixture("/api/v1/auths/me", "get", 200, {
  status: "success",
  message: "Profile loaded",
  data: {
    user: { id: "usr_example" },
    profile: { display_name: "Example User", avatar_url: null },
    session: { id: "ses_example", expires_at: "2026-08-13T12:00:00Z" },
    workspace: {
      id: "wsp_example",
      name: "Personal Workspace",
      role: "owner",
      capabilities: ["workspace:manage"],
    },
  },
}).body;

const profileResponse = defineApiFixture("/api/v1/auths/me/profile", "patch", 200, {
  status: "success",
  message: "Profile updated",
  data: { display_name: "Updated User", avatar_url: "https://media.example/avatar" },
}).body;

const authorizationStartResponse = defineApiFixture("/api/v1/auths/sign-in/{provider}", "post", 200, {
  status: "success",
  message: "Authentication started",
  data: { redirect_url: "https://accounts.google.com/o/oauth2/v2/auth" },
}).body;

const preparedAvatarResponse = defineApiFixture("/api/v1/auths/me/avatar/uploads", "post", 201, {
  status: "success",
  message: "Avatar upload prepared",
  data: {
    asset_id: "avt_example",
    upload_url: "https://uploads.example/avatar",
    headers: { "Content-Type": "image/png" },
    expires_at: "2026-08-13T12:00:00Z",
  },
}).body;

const completedAvatarResponse = defineApiFixture(
  "/api/v1/auths/me/avatar/{asset_id}/complete",
  "post",
  200,
  {
  status: "success",
  message: "Avatar loaded",
  data: {
    asset_id: "avt_example",
    url: "https://media.example/avatar",
    expires_at: "2026-08-13T12:00:00Z",
  },
  },
).body;

const readAvatarResponse = defineApiFixture("/api/v1/auths/me/avatar/read", "get", 200, completedAvatarResponse).body;

const workspaceResponse = defineApiFixture("/api/v1/workspaces/{workspace_id}", "get", 200, {
  status: "success",
  message: "Workspace loaded",
  data: {
    id: "wsp_example",
    name: "Personal Workspace",
    role: "owner",
    capabilities: ["workspace:manage"],
  },
}).body;

const errorResponse = {
  status: "error",
  message: "Authentication required",
  data: null,
} as const;

const errorFixtures = [
  [defineApiFixture("/api/v1/auths/csrf", "get", 429, errorResponse), "throttled"],
  [defineApiFixture("/api/v1/auths/sign-in/{provider}", "post", 400, errorResponse), "bad-request"],
  [defineApiFixture("/api/v1/auths/refresh", "post", 401, errorResponse), "unauthorized"],
  [defineApiFixture("/api/v1/auths/logout", "post", 403, errorResponse), "forbidden"],
  [defineApiFixture("/api/v1/auths/me", "get", 401, errorResponse), "unauthorized"],
  [defineApiFixture("/api/v1/auths/me/profile", "patch", 401, errorResponse), "unauthorized"],
  [defineApiFixture("/api/v1/auths/me/avatar/uploads", "post", 401, errorResponse), "unauthorized"],
  [defineApiFixture("/api/v1/auths/me/avatar/{asset_id}/complete", "post", 401, errorResponse), "unauthorized"],
  [defineApiFixture("/api/v1/auths/me/avatar/read", "get", 401, errorResponse), "unauthorized"],
  [defineApiFixture("/api/v1/auths/me/avatar", "delete", 401, errorResponse), "unauthorized"],
  [defineApiFixture("/api/v1/workspaces/{workspace_id}", "get", 404, errorResponse), "not-found"],
] as const;

const csrfSuccess = defineApiFixture("/api/v1/auths/csrf", "get", 204, undefined);
const refreshSuccess = defineApiFixture("/api/v1/auths/refresh", "post", 204, undefined);
const logoutSuccess = defineApiFixture("/api/v1/auths/logout", "post", 204, undefined);
const deleteAvatarSuccess = defineApiFixture("/api/v1/auths/me/avatar", "delete", 204, undefined);

describe("createCloudClient", () => {
  it("maps a typed current-account response", async () => {
    const fetch = vi.fn(async () => Response.json(accountResponse));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.getCurrentAccount()).resolves.toMatchObject({
      userId: "usr_example",
      workspace: { id: "wsp_example" },
    });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("binds the default global fetch before calling it", async () => {
    const originalFetch = globalThis.fetch;
    const fetch = vi.fn(function (this: typeof globalThis) {
      expect(this).toBe(globalThis);
      return Promise.resolve(Response.json(accountResponse));
    }) as typeof globalThis.fetch;
    globalThis.fetch = fetch;

    try {
      const client = createCloudClient({ baseUrl: "https://cloud.example.com" });

      await expect(client.getCurrentAccount()).resolves.toMatchObject({
        userId: "usr_example",
      });
      expect(fetch).toHaveBeenCalledOnce();
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("maps every exported account, avatar, and Workspace success operation", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const path = new URL(request.url).pathname;
      if (path.includes("/auths/sign-in/")) return Response.json(authorizationStartResponse);
      if (request.method === "PATCH") return Response.json(profileResponse);
      if (path.endsWith("/avatar/uploads")) return Response.json(preparedAvatarResponse);
      if (path.endsWith("/complete")) return Response.json(completedAvatarResponse);
      if (path.endsWith("/avatar/read")) return Response.json(readAvatarResponse);
      if (request.method === "DELETE") return new Response(null, { status: deleteAvatarSuccess.status });
      if (path.startsWith("/api/v1/workspaces/")) return Response.json(workspaceResponse);
      if (path.endsWith("/csrf")) {
        return new Response(null, {
          status: csrfSuccess.status,
          headers: { "X-CSRFToken": "a".repeat(32) },
        });
      }
      if (path.endsWith("/refresh")) return new Response(null, { status: refreshSuccess.status });
      if (path.endsWith("/logout")) return new Response(null, { status: logoutSuccess.status });
      throw new Error(`Unexpected request: ${request.method} ${path}`);
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.getCsrf()).resolves.toBe("a".repeat(32));
    await expect(client.beginSignIn("/account")).resolves.toBe(authorizationStartResponse.data.redirect_url);
    await expect(client.refreshSession()).resolves.toBeUndefined();
    await expect(client.logout()).resolves.toBeUndefined();
    await expect(client.updateProfile("Updated User")).resolves.toEqual({
      displayName: "Updated User",
      avatarUrl: "https://media.example/avatar",
    });
    await expect(client.prepareAvatarUpload({
      contentType: "image/png",
      size: 128,
      sha256: "a".repeat(64),
    })).resolves.toMatchObject({ assetId: "avt_example" });
    await expect(client.completeAvatar("avt_example")).resolves.toMatchObject({ assetId: "avt_example" });
    await expect(client.getAvatarRead()).resolves.toMatchObject({ assetId: "avt_example" });
    await expect(client.deleteAvatar()).resolves.toBeUndefined();
    await expect(client.getWorkspace("wsp_example")).resolves.toEqual(workspaceResponse.data);
  });

  it("sends a strict content-free runtime intent and maps its bounded result", async () => {
    const idempotencyKey = "00000000-0000-4000-8000-000000000001";
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      expect(new URL(request.url).pathname).toBe("/api/v1/allies/ally_example/runtime-intents");
      expect(request.method).toBe("POST");
      expect(request.headers.get("Idempotency-Key")).toBe(idempotencyKey);
      expect(await request.clone().json()).toEqual({
        intent: "composing_started",
        occurred_at: "2026-09-04T12:00:00.000Z",
      });
      return Response.json({
        status: "success",
        message: "Runtime intent accepted",
        data: { status: "waking" },
      }, { status: 202 });
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.requestRuntimeIntent(
      "ally_example",
      "2026-09-04T12:00:00.000Z",
      idempotencyKey,
    )).resolves.toEqual({ status: "waking" });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("sends a workspace creation intent without Ally draft content", async () => {
    const idempotencyKey = "00000000-0000-4000-8000-000000000002";
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      expect(new URL(request.url).pathname).toBe("/api/v1/onboarding/runtime-intents");
      expect(request.method).toBe("POST");
      expect(request.headers.get("Idempotency-Key")).toBe(idempotencyKey);
      expect(await request.clone().json()).toEqual({
        version: 1,
        intent: "ally_creation_started",
        occurred_at: "2026-09-04T12:00:00.000Z",
      });
      return Response.json({
        status: "success",
        message: "Runtime intent accepted",
        data: { status: "waking" },
      }, { status: 202 });
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.requestWorkspaceRuntimeIntent(
      "2026-09-04T12:00:00.000Z",
      idempotencyKey,
    )).resolves.toEqual({ status: "waking" });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("rejects malformed runtime-intent input and response before exposing it", async () => {
    const idempotencyKey = "00000000-0000-4000-8000-000000000001";
    const fetch = vi.fn(async () => Response.json({
      status: "success",
      message: "Runtime intent accepted",
      data: { status: "provider_detail" },
    }, { status: 200 }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.requestRuntimeIntent("ally_example", "not-a-timestamp", idempotencyKey))
      .rejects.toMatchObject({ kind: "bad-request" });
    expect(fetch).not.toHaveBeenCalled();
    await expect(client.requestRuntimeIntent("ally_example", "2026-09-04T12:00:00.000Z", idempotencyKey))
      .rejects.toMatchObject({ kind: "contract" });
  });

  it("normalizes a contract-declared failure for every exported operation", async () => {
    const operations = [
      (client: ReturnType<typeof createCloudClient>) => client.getCsrf(),
      (client: ReturnType<typeof createCloudClient>) => client.beginSignIn("/account"),
      (client: ReturnType<typeof createCloudClient>) => client.refreshSession(),
      (client: ReturnType<typeof createCloudClient>) => client.logout(),
      (client: ReturnType<typeof createCloudClient>) => client.getCurrentAccount(),
      (client: ReturnType<typeof createCloudClient>) => client.updateProfile("Updated User"),
      (client: ReturnType<typeof createCloudClient>) => client.prepareAvatarUpload({
        contentType: "image/png",
        size: 128,
        sha256: "a".repeat(64),
      }),
      (client: ReturnType<typeof createCloudClient>) => client.completeAvatar("avt_example"),
      (client: ReturnType<typeof createCloudClient>) => client.getAvatarRead(),
      (client: ReturnType<typeof createCloudClient>) => client.deleteAvatar(),
      (client: ReturnType<typeof createCloudClient>) => client.getWorkspace("wsp_example"),
    ];

    for (const [index, operation] of operations.entries()) {
      const [fixture, expectedKind] = errorFixtures[index];
      const client = createCloudClient({
        baseUrl: "https://cloud.example.com",
        fetch: async () => Response.json(fixture.body, { status: fixture.status }),
      });
      await expect(operation(client)).rejects.toMatchObject({ kind: expectedKind, status: fixture.status });
    }
  });

  it("turns malformed successes into contract errors", async () => {
    const fetch = vi.fn(async () => Response.json({ ...accountResponse, data: { user: {} } }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.getCurrentAccount()).rejects.toMatchObject({ kind: "contract" });
  });

  it("rejects oversized JSON before mapping it", async () => {
    const fetch = vi.fn(async () => new Response("x".repeat(257 * 1024), {
      headers: { "content-type": "application/json" },
    }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.getCurrentAccount()).rejects.toMatchObject({ kind: "contract" });
  });

  it("keeps browser request preparation app-owned", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(input);
      expect(request.credentials).toBe("include");
      expect(request.headers.get("x-csrftoken")).toBe("csrf-value");
      return new Response(null, { status: 204 });
    });
    const client = createCloudClient({
      baseUrl: "https://cloud.example.com",
      fetch,
      prepareRequest: (request) => {
        const headers = new Headers(request.headers);
        headers.set("x-csrftoken", "csrf-value");
        return new Request(request, { credentials: "include", headers });
      },
    });

    await client.logout();
  });

  it.each([undefined, "short", "a".repeat(31), "a".repeat(33), "a".repeat(63), "a".repeat(65), "a".repeat(31) + "!"])(
    "rejects a missing or malformed exposed CSRF header: %s",
    async (header) => {
      const client = createCloudClient({
        baseUrl: "https://cloud.example.com",
        fetch: async () => new Response(null, {
          status: 204,
          headers: header ? { "X-CSRFToken": header } : undefined,
        }),
      });

      await expect(client.getCsrf()).rejects.toMatchObject({ kind: "contract" });
    },
  );

  it("rejects a CSRF response that is not the contract's 204", async () => {
    const client = createCloudClient({
      baseUrl: "https://cloud.example.com",
      fetch: async () => new Response(null, {
        status: 200,
        headers: { "X-CSRFToken": "a".repeat(32) },
      }),
    });

    await expect(client.getCsrf()).rejects.toMatchObject({ kind: "contract" });
  });

  it("distinguishes timeout, caller abort, and network failures", async () => {
    const hangingFetch: typeof fetch = async (input) => {
      const request = input instanceof Request ? input : new Request(input);
      return new Promise<Response>((_resolve, reject) => {
        request.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      });
    };
    const timeoutClient = createCloudClient({
      baseUrl: "https://cloud.example.com",
      fetch: hangingFetch,
      timeoutMs: 1,
    });
    await expect(timeoutClient.getCurrentAccount()).rejects.toMatchObject({ kind: "timeout" });

    const controller = new AbortController();
    const abortClient = createCloudClient({ baseUrl: "https://cloud.example.com", fetch: hangingFetch });
    const request = abortClient.getCurrentAccount(controller.signal);
    controller.abort();
    await expect(request).rejects.toMatchObject({ kind: "aborted" });

    const networkClient = createCloudClient({
      baseUrl: "https://cloud.example.com",
      fetch: async () => { throw new TypeError("socket failed"); },
    });
    await expect(networkClient.getCurrentAccount()).rejects.toMatchObject({ kind: "network" });
  });

  it("bounds response-body stalls with timeout and caller cancellation", async () => {
    const stalledBodyFetch: typeof fetch = async () => new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('{"status":"success"'));
      },
    }), { headers: { "content-type": "application/json" } });

    const timeoutClient = createCloudClient({
      baseUrl: "https://cloud.example.com",
      fetch: stalledBodyFetch,
      timeoutMs: 5,
    });
    await expect(timeoutClient.getCurrentAccount()).rejects.toMatchObject({ kind: "timeout" });

    const controller = new AbortController();
    const abortClient = createCloudClient({ baseUrl: "https://cloud.example.com", fetch: stalledBodyFetch });
    const request = abortClient.getCurrentAccount(controller.signal);
    controller.abort();
    await expect(request).rejects.toMatchObject({ kind: "aborted" });
  });

  it("does not send a request when the caller signal is already aborted", async () => {
    const fetch = vi.fn(async () => Response.json(accountResponse));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });
    const controller = new AbortController();
    controller.abort();

    await expect(client.getCurrentAccount(controller.signal)).rejects.toMatchObject({ kind: "aborted" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([
    "https://evil.example",
    "//evil.example",
    "\\evil.example",
    "/%2F%2Fevil.example",
    "/%5Cevil.example",
    "/%252F%252Fevil.example",
    "/%25252F%25252Fevil.example",
    "/%25252525252525252F%25252525252525252Fevil.example",
    "/%not-encoded",
  ])(
    "rejects an unsafe sign-in return target: %s",
    async (redirectTo) => {
      const fetch = vi.fn(async () => Response.json(accountResponse));
      const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

      await expect(client.beginSignIn(redirectTo)).rejects.toMatchObject({ kind: "bad-request" });
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it.each([
    "/account",
    "/account?next=%2Fworkspace#details",
    "/foo%20bar",
  ])("accepts a safe root-relative return target: %s", (value) => {
    expect(parseSafeReturnPath(value)).toBe(value);
  });

  it.each([
    undefined,
    "",
    "//evil.example",
    "\\\\evil.example",
    "/contains\nnewline",
    "/%0A",
    "/%not-encoded",
    "/" + "a".repeat(500),
    "/%2525252525252525252525252525252F%2525252525252525252525252525252Fevil.example",
  ])("returns null for an unsafe return target: %s", (value) => {
    expect(parseSafeReturnPath(value)).toBeNull();
  });

  it.each(["javascript:alert(1)", "data:text/html,unsafe", "http://accounts.google.com/auth"])(
    "rejects an unsafe provider redirect: %s",
    async (redirectUrl) => {
      const fetch = vi.fn(async () =>
        Response.json({
          status: "success",
          message: "Authentication started",
          data: { redirect_url: redirectUrl },
        }),
      );
      const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });

      await expect(client.beginSignIn("/account")).rejects.toMatchObject({ kind: "contract" });
    },
  );

  it.each([
    "http://media.example/avatar",
    "file:///tmp/avatar.png",
    "https://user:password@media.example/avatar",
  ])("rejects unsafe avatar and upload URLs: %s", async (unsafeUrl) => {
    const responses = [
      { ...accountResponse, data: { ...accountResponse.data, profile: { ...accountResponse.data.profile, avatar_url: unsafeUrl } } },
      { ...profileResponse, data: { ...profileResponse.data, avatar_url: unsafeUrl } },
      { ...preparedAvatarResponse, data: { ...preparedAvatarResponse.data, upload_url: unsafeUrl } },
      { ...readAvatarResponse, data: { ...readAvatarResponse.data, url: unsafeUrl } },
    ];
    const calls = [
      (client: ReturnType<typeof createCloudClient>) => client.getCurrentAccount(),
      (client: ReturnType<typeof createCloudClient>) => client.updateProfile("Updated User"),
      (client: ReturnType<typeof createCloudClient>) => client.prepareAvatarUpload({
        contentType: "image/png",
        size: 128,
        sha256: "a".repeat(64),
      }),
      (client: ReturnType<typeof createCloudClient>) => client.getAvatarRead(),
    ];

    for (const [index, call] of calls.entries()) {
      const client = createCloudClient({
        baseUrl: "https://cloud.example.com",
        fetch: async () => Response.json(responses[index]),
      });
      await expect(call(client)).rejects.toMatchObject({ kind: "contract" });
    }
  });
});
