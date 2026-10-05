import { describe, expect, it, vi } from "vitest";

import { createNativeAuthClient } from "../src/native-auth";

const tokens = {
  token_type: "Bearer",
  access_token: "access-example",
  expires_in: 600,
  refresh_token: "refresh-example",
  refresh_expires_in: 1209600,
  session_id: "ses_example",
};

describe("createNativeAuthClient", () => {
  it("starts Google auth without cookies or bearer credentials", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      expect(request.method).toBe("POST");
      expect(new URL(request.url).pathname).toBe("/api/v1/auths/native/sign-in/google");
      expect(request.credentials).toBe("omit");
      expect(request.headers.get("authorization")).toBeNull();
      expect(request.headers.get("cookie")).toBeNull();
      expect(await request.json()).toEqual({
        redirect_uri: "https://mobile.example/auth/return",
        code_challenge: "a".repeat(43),
        code_challenge_method: "S256",
        state: "state-example",
      });
      return Response.json({
        status: "success",
        message: "Native sign-in started",
        data: {
          authorization_url: "https://accounts.google.com/o/oauth2/auth",
          expires_at: "2026-08-21T12:00:00Z",
        },
      });
    });
    const client = createNativeAuthClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.beginGoogleSignIn({
      redirectUri: "https://mobile.example/auth/return",
      codeChallenge: "a".repeat(43),
      state: "state-example",
    })).resolves.toEqual({
      authorizationUrl: "https://accounts.google.com/o/oauth2/auth",
      expiresAt: "2026-08-21T12:00:00Z",
    });
  });

  it("maps token exchange and refresh responses", async () => {
    const fetch = vi.fn(async () => Response.json({
      status: "success",
      message: "Native session issued",
      data: tokens,
    }));
    const client = createNativeAuthClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.exchangeGoogleCode({
      code: "code-example",
      codeVerifier: "verifier-example",
      redirectUri: "https://mobile.example/auth/return",
    })).resolves.toEqual({
      tokenType: "Bearer",
      accessToken: "access-example",
      expiresIn: 600,
      refreshToken: "refresh-example",
      refreshExpiresIn: 1209600,
      sessionId: "ses_example",
    });
    await expect(client.refreshSession("refresh-example")).resolves.toMatchObject({
      accessToken: "access-example",
    });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("sends the refresh body and matching bearer for logout", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      expect(new URL(request.url).pathname).toBe("/api/v1/auths/native/logout");
      expect(request.credentials).toBe("omit");
      expect(request.headers.get("authorization")).toBe("Bearer access-example");
      expect(await request.json()).toEqual({ refresh_token: "refresh-example" });
      return new Response(null, { status: 204 });
    });
    const client = createNativeAuthClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.logout("refresh-example", "access-example")).resolves.toBeUndefined();
  });

  it("rejects an unsafe authorization URL as a contract error", async () => {
    const fetch = vi.fn(async () => Response.json({
      status: "success",
      message: "Native sign-in started",
      data: {
        authorization_url: "http://accounts.google.com/auth",
        expires_at: "2026-08-21T12:00:00Z",
      },
    }));
    const client = createNativeAuthClient({ baseUrl: "https://cloud.example.com", fetch });

    await expect(client.beginGoogleSignIn({
      redirectUri: "https://mobile.example/auth/return",
      codeChallenge: "a".repeat(43),
      state: "state-example",
    })).rejects.toMatchObject({ kind: "contract" });
  });
});
