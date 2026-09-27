import { describe, expect, it, vi } from "vitest";

import { createCloudClient } from "../src/client";
import { parseGoogleAuthUrl } from "../src/mappers/gmail";

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

describe("gmail integration client", () => {
  it("treats a null status as not connected and maps a live connection", async () => {
    const empty = clientFor(() => Response.json({ status: "success", message: "ok", data: null }));
    await expect(empty.client.getGmailConnection(workspaceId)).resolves.toBeNull();
    const live = clientFor(() => Response.json({ status: "success", message: "ok", data: connection }));
    await expect(live.client.getGmailConnection(workspaceId)).resolves.toMatchObject({
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
    await expect(client.beginGmailConnect(workspaceId, { allyId, grantLevel: "read", returnTo: `/home/${allyId}` }, key))
      .resolves.toMatchObject({ authUrl: "https://accounts.google.com/o/oauth2/v2/auth?state=abc" });
  });

  it("refuses to hand back a consent url that is not Google's", async () => {
    const { client } = clientFor(() => Response.json({ status: "success", message: "ok", data: {
      connect_session_id: "00000000-0000-4000-8000-000000000004",
      auth_url: "https://accounts.google.com.evil.example/auth",
      expires_at: "2026-09-20T10:10:00Z",
    } }, { status: 202 }));
    await expect(client.beginGmailConnect(workspaceId, { allyId, grantLevel: "read", returnTo: `/home/${allyId}` }, key))
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
    await expect(client.setGmailGrant(workspaceId, allyId, "none")).rejects.toMatchObject({ kind: "contract" });
  });

});
