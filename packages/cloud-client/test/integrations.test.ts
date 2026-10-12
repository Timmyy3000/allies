import { describe, expect, it, vi } from "vitest";

import { createCloudClient } from "../src/client";
import { parseGoogleAuthUrl } from "../src/mappers/integrations";

const workspaceId = "00000000-0000-4000-8000-000000000001";
const allyId = "00000000-0000-4000-8000-000000000002";
const key = "11111111-1111-4111-8111-111111111111";
const connection = {
  connection_id: "00000000-0000-4000-8000-000000000003",
  account_email: "me@example.com",
  scope_set: ["gmail.readonly", "gmail.send"],
  connected_at: "2026-09-20T10:00:00Z",
  ally_grants: [{ ally_id: allyId, level: "read", grant_generation: 1, updated_at: "2026-09-20T10:00:00Z" }],
};

function clientFor(handler: (request: Request) => Promise<Response> | Response) {
  const fetch = vi.fn(handler);
  return { fetch, client: createCloudClient({ baseUrl: "https://cloud.example.com", fetch: fetch as typeof globalThis.fetch }) };
}

describe("integration client", () => {
  it("treats a null status as not connected and maps a live connection", async () => {
    const empty = clientFor(() => Response.json({ status: "success", message: "ok", data: null }));
    await expect(empty.client.getIntegrationConnection(workspaceId, "gmail")).resolves.toBeNull();
    const live = clientFor(() => Response.json({ status: "success", message: "ok", data: connection }));
    await expect(live.client.getIntegrationConnection(workspaceId, "gmail")).resolves.toMatchObject({
      accountEmail: "me@example.com",
      allyGrants: [{ allyId, level: "read" }],
    });
  });

  it("starts an in-chat connect for one Ally with the idempotency key", async () => {
    const { client } = clientFor(async (request) => {
      expect(request.headers.get("Idempotency-Key")).toBe(key);
      expect(await request.json()).toEqual({ entry_point: "in_chat", ally_id: allyId, grant_level: "read", return_to: `/home/${allyId}` });
      return Response.json({ status: "success", message: "ok", data: {
        connect_session_id: "00000000-0000-4000-8000-000000000004",
        auth_url: "https://accounts.google.com/o/oauth2/v2/auth?state=abc",
        expires_at: "2026-09-20T10:10:00Z",
      } }, { status: 202 });
    });
    await expect(client.beginIntegrationConnect(workspaceId, "gmail", { allyId, grantLevel: "read", returnTo: `/home/${allyId}` }, key))
      .resolves.toMatchObject({ authUrl: "https://accounts.google.com/o/oauth2/v2/auth?state=abc" });
  });

  it("starts an account-level connect from settings without an Ally", async () => {
    const { client } = clientFor(async (request) => {
      expect(await request.json()).toEqual({ entry_point: "integrations", return_to: "/account" });
      return Response.json({ status: "success", message: "ok", data: {
        connect_session_id: "00000000-0000-4000-8000-000000000004",
        auth_url: "https://accounts.google.com/o/oauth2/v2/auth?state=abc",
        expires_at: "2026-09-20T10:10:00Z",
      } }, { status: 202 });
    });
    await expect(client.beginIntegrationConnect(workspaceId, "gmail", { grantLevel: "read", returnTo: "/account" }, key))
      .resolves.toMatchObject({ connectSessionId: "00000000-0000-4000-8000-000000000004" });
  });

  it("disconnects Gmail for the workspace", async () => {
    const { client, fetch } = clientFor(() => Response.json({ status: "success", message: "ok", data: { status: "disconnecting" } }, { status: 202 }));
    await expect(client.disconnectIntegration(workspaceId, "gmail")).resolves.toBeUndefined();
    const request = fetch.mock.calls[0]?.[0] as Request;
    expect(request.method).toBe("DELETE");
    expect(await request.json()).toEqual({ confirm: true });
    expect(new URL(request.url).pathname).toBe(`/api/v1/workspaces/${workspaceId}/integrations/gmail`);
  });

  it("refuses to hand back a consent url that is not Google's", async () => {
    const { client } = clientFor(() => Response.json({ status: "success", message: "ok", data: {
      connect_session_id: "00000000-0000-4000-8000-000000000004",
      auth_url: "https://accounts.google.com.evil.example/auth",
      expires_at: "2026-09-20T10:10:00Z",
    } }, { status: 202 }));
    await expect(client.beginIntegrationConnect(workspaceId, "gmail", { allyId, grantLevel: "read", returnTo: `/home/${allyId}` }, key))
      .rejects.toMatchObject({ kind: "contract" });
  });

  it.each([
    "http://accounts.google.com/auth",
    "https://evil.example/?x=https://accounts.google.com",
    "https://user@accounts.google.com/auth",
    "https://accounts.google.com:8443/auth",
    "javascript:alert(1)",
    "not a url",
  ])("rejects unsafe consent url %s", (value) => {
    expect(parseGoogleAuthUrl(value)).toBeNull();
  });

  it("rejects a grant response for a different Ally", async () => {
    const { client } = clientFor(async (request) => {
      expect(await request.json()).toEqual({ ally_id: allyId, level: "none" });
      return Response.json({ status: "success", message: "ok", data: {
        ally_id: "00000000-0000-4000-8000-000000000009", level: "none", grant_generation: 0, updated_at: "2026-09-20T10:00:00Z",
      } });
    });
    await expect(client.setIntegrationGrant(workspaceId, "gmail", allyId, "none")).rejects.toMatchObject({ kind: "contract" });
  });

  it("connects, grants write on, and disconnects Calendar through its own routes", async () => {
    const { client, fetch } = clientFor(async (request) => {
      const { pathname } = new URL(request.url);
      if (pathname.endsWith("/calendar/connect")) {
        expect(await request.json()).toEqual({ entry_point: "in_chat", ally_id: allyId, grant_level: "write", return_to: `/home/${allyId}` });
        return Response.json({ status: "success", message: "ok", data: {
          connect_session_id: "00000000-0000-4000-8000-000000000004",
          auth_url: "https://accounts.google.com/o/oauth2/v2/auth?state=abc",
          expires_at: "2026-09-20T10:10:00Z",
        } }, { status: 202 });
      }
      if (pathname.endsWith("/calendar/grants")) {
        expect(await request.json()).toEqual({ ally_id: allyId, level: "write" });
        return Response.json({ status: "success", message: "ok", data: {
          ally_id: allyId, level: "write", grant_generation: 2, updated_at: "2026-09-20T10:00:00Z",
        } });
      }
      return Response.json({ status: "success", message: "ok", data: null });
    });
    await client.beginIntegrationConnect(workspaceId, "calendar", { allyId, grantLevel: "write", returnTo: `/home/${allyId}` }, key);
    await expect(client.setIntegrationGrant(workspaceId, "calendar", allyId, "write")).resolves.toMatchObject({ level: "write" });
    await expect(client.getIntegrationConnection(workspaceId, "calendar")).resolves.toBeNull();
    await client.disconnectIntegration(workspaceId, "calendar");
    const paths = fetch.mock.calls.map(([request]) => new URL((request as Request).url).pathname);
    expect(paths).toEqual([
      `/api/v1/workspaces/${workspaceId}/integrations/calendar/connect`,
      `/api/v1/workspaces/${workspaceId}/integrations/calendar/grants`,
      `/api/v1/workspaces/${workspaceId}/integrations/calendar`,
      `/api/v1/workspaces/${workspaceId}/integrations/calendar`,
    ]);
  });

  it("refuses an unknown provider before any request", async () => {
    const { client, fetch } = clientFor(() => Response.json({}));
    await expect(client.getIntegrationConnection(workspaceId, "drive" as never)).rejects.toBeDefined();
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("web search client", () => {
  const webSearchPath = `/api/v1/workspaces/${workspaceId}/integrations/web-search`;
  const webSearchConnection = {
    connection_id: "00000000-0000-4000-8000-000000000005",
    backend: "parallel",
    key_hint: "x9Qa",
    connected_at: "2026-10-12T10:00:00Z",
    ally_grants: [{ ally_id: allyId, level: "use", grant_generation: 1, updated_at: "2026-10-12T10:05:00Z" }],
  };
  const apiKey = "pk_live_example_key_x9Qa";

  it("maps a live web search connection and treats null as not connected", async () => {
    const empty = clientFor(() => Response.json({ status: "success", message: "ok", data: null }));
    await expect(empty.client.getWebSearchConnection(workspaceId)).resolves.toBeNull();
    expect(new URL((empty.fetch.mock.calls[0]?.[0] as Request).url).pathname).toBe(webSearchPath);

    const live = clientFor(() => Response.json({ status: "success", message: "ok", data: webSearchConnection }));
    await expect(live.client.getWebSearchConnection(workspaceId)).resolves.toEqual({
      backend: "parallel",
      keyHint: "x9Qa",
      connectedAt: "2026-10-12T10:00:00Z",
      allyGrants: [{ allyId, level: "use", grantGeneration: 1, updatedAt: "2026-10-12T10:05:00Z" }],
    });
  });

  it("sends the key once with the chosen provider and returns only its hint", async () => {
    const { client, fetch } = clientFor(async (request) => {
      expect(await request.json()).toEqual({ backend: "tavily", api_key: apiKey });
      return Response.json({ status: "success", message: "ok", data: { ...webSearchConnection, backend: "tavily" } });
    });
    const saved = await client.connectWebSearch(workspaceId, { backend: "tavily", apiKey });
    expect(saved).toMatchObject({ backend: "tavily", keyHint: "x9Qa" });
    expect(JSON.stringify(saved)).not.toContain(apiKey);
    expect((fetch.mock.calls[0]?.[0] as Request).method).toBe("PUT");
  });

  it("surfaces a rejected key with its Cloud code", async () => {
    const { client } = clientFor(() => Response.json(
      { status: "error", message: "Parallel rejected this key.", data: { code: "web_search_key_rejected" } },
      { status: 422 },
    ));
    await expect(client.connectWebSearch(workspaceId, { backend: "parallel", apiKey }))
      .rejects.toMatchObject({ kind: "validation", status: 422, code: "web_search_key_rejected" });
  });

  it("refuses a key outside the Cloud length and character rule before any request", async () => {
    const { client, fetch } = clientFor(() => Response.json({}));
    await expect(client.connectWebSearch(workspaceId, { backend: "exa", apiKey: "too-short" }))
      .rejects.toMatchObject({ kind: "bad-request" });
    await expect(client.connectWebSearch(workspaceId, { backend: "exa", apiKey: `${apiKey} with space` }))
      .rejects.toMatchObject({ kind: "bad-request" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("grants and ungrants web search per Ally", async () => {
    const { client, fetch } = clientFor(async (request) => {
      expect(await request.json()).toEqual({ ally_id: allyId, level: "none" });
      return Response.json({ status: "success", message: "ok", data: {
        ally_id: allyId, level: "none", grant_generation: 0, updated_at: "2026-10-12T10:05:00Z",
      } });
    });
    await expect(client.setWebSearchGrant(workspaceId, allyId, "none")).resolves.toMatchObject({ allyId, level: "none" });
    expect(new URL((fetch.mock.calls[0]?.[0] as Request).url).pathname).toBe(`${webSearchPath}/grants`);
  });

  it("disconnects web search with confirmation", async () => {
    const { client, fetch } = clientFor(() => Response.json({ status: "success", message: "ok", data: { status: "deprovisioned" } }, { status: 202 }));
    await expect(client.disconnectWebSearch(workspaceId)).resolves.toBeUndefined();
    const request = fetch.mock.calls[0]?.[0] as Request;
    expect(request.method).toBe("DELETE");
    expect(new URL(request.url).pathname).toBe(webSearchPath);
    expect(await request.json()).toEqual({ confirm: true });
  });
});
